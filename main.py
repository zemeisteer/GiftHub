import argparse
import asyncio
import logging
import signal
import socket

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiohttp.resolver import DefaultResolver

from app import handlers
from app.core.config import settings
from app.core.database import engine
from app.core.redis import get_fsm_storage
from app.services.worker import run_worker_loop, stop_worker
from app.utils.misc.logging import setup_logger
from app.utils.notify_admins import notify_admins
from app.utils.set_bot_commands import set_bot_commands
from app.web.server import app as fastapi_app
from app.web.server import set_bot
from data import config
from database.db import init_db
from middlewares import setup_middlewares

TELEGRAM_FAST_IPS = ["149.154.166.110", "149.154.167.99", "149.154.167.222", "149.154.166.120"]


class DirectTelegramResolver(DefaultResolver):
    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        if host == "api.telegram.org":
            try:
                res = await super().resolve(host, port, family)
                if res:
                    return res
            except Exception as e:
                logging.debug(f"DirectTelegramResolver DNS resolution fallback ({e})")
            return [
                {"hostname": host, "host": ip, "port": port, "family": socket.AF_INET, "proto": 0, "flags": 0}
                for ip in TELEGRAM_FAST_IPS
            ]
        return await super().resolve(host, port, family)


class DirectTelegramSession(AiohttpSession):
    async def create_session(self):
        if "resolver" not in self._connector_init:
            self._connector_init["resolver"] = DirectTelegramResolver()
            self._connector_init["family"] = socket.AF_INET
        return await super().create_session()


bot_session = None
if config.TELEGRAM_API_SERVER:
    api_server = TelegramAPIServer.from_base(config.TELEGRAM_API_SERVER)
    bot_session = AiohttpSession(api=api_server)
elif config.TELEGRAM_PROXY:
    bot_session = AiohttpSession(proxy=config.TELEGRAM_PROXY)
else:
    bot_session = DirectTelegramSession()

bot = Bot(token=config.BOT_TOKEN, session=bot_session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = get_fsm_storage()
dp = Dispatcher(storage=storage)

web_server: uvicorn.Server | None = None

# Web server (lifespan shutdown) va worker (joriy outbox/to'lov siklini tugatish) uchun
# beriladigan umumiy vaqt (soniya). docker-compose'dagi stop_grace_period bundan katta bo'lishi kerak.
GRACEFUL_SHUTDOWN_TIMEOUT = 25


def request_web_server_exit():
    """Uvicorn serverini graceful to'xtatishni so'raydi (task'ni cancel qilmasdan)."""
    if web_server is not None:
        web_server.should_exit = True


async def start_web_server():
    global web_server
    server_config = uvicorn.Config(app=fastapi_app, host=config.WEB_HOST, port=config.WEB_PORT, log_level="info")
    web_server = uvicorn.Server(server_config)
    await web_server.serve()


async def start_bot(shutdown_event: asyncio.Event = None):
    try:
        try:
            bot_info = await bot.get_me()
            set_bot(bot, bot_info.username)
            logging.info(f"🤖 Telegram Bot: @{bot_info.username}")
        except Exception as e:
            logging.warning(f"Bot info olishda ogohlantirish: {e}")

        await set_bot_commands(bot)

        # Pastki "Menu" tugmasi: do'kon (Web App) ochiq bo'lsa uni ochadi, aks holda buyruqlar ro'yxati
        try:
            from aiogram.types import MenuButtonWebApp

            from app.keyboards.shop_keyboards import get_chat_menu_button

            menu_button = get_chat_menu_button()
            await bot.set_chat_menu_button(menu_button=menu_button)
            if isinstance(menu_button, MenuButtonWebApp):
                logging.info(f"✅ Telegram Menu tugmasi do'konni ochadi: {menu_button.web_app.url}")
            else:
                logging.info("✅ Telegram Menu tugmasi buyruqlar menyusiga sozlandi (HTTPS Web App manzili yo'q).")
        except Exception as err:
            logging.warning(f"Chat menu button sozlashda ogohlantirish: {err}")

        await notify_admins(bot)

        # Webhook vs Polling Mode (Req 14 & Req 13)
        if settings.TELEGRAM_MODE == "webhook" and settings.TELEGRAM_WEBHOOK_URL:
            webhook_url = f"{settings.TELEGRAM_WEBHOOK_URL.rstrip('/')}/webhook/telegram"
            await bot.set_webhook(
                url=webhook_url,
                secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
                drop_pending_updates=settings.DROP_PENDING_UPDATES,
            )
            logging.info(f"✅ Telegram Webhook rejimida ulandi: {webhook_url}")
            # Webhook rejimida yangilanishlarni API server qabul qiladi. Bu task darhol tugasa,
            # main() dagi FIRST_COMPLETED butun ilovani (API serverni ham) to'xtatib qo'yardi.
            if shutdown_event:
                await shutdown_event.wait()
        else:
            await bot.delete_webhook(drop_pending_updates=settings.DROP_PENDING_UPDATES)
            logging.info(f"✅ Telegram Polling boshlandi (drop_pending_updates={settings.DROP_PENDING_UPDATES})")
            # Signallarni main() boshqaradi; bot sessiyasini cleanup_resources() yopadi
            # (worker ham shu sessiyadan foydalanadi).
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
                handle_signals=False,
                close_bot_session=False,
            )

    except asyncio.CancelledError:
        raise
    except TelegramUnauthorizedError:
        logging.warning(
            "⚠️ BOT_TOKEN yaroqsiz yoki test tokeni kiritilgan. Bot to'xtatildi, lekin API serveri ishlashda davom etadi!"
        )
        logging.info("👉 Iltimos, Telegram @BotFather dan yangi token olib, .env faylidagi BOT_TOKEN ga kiriting.")
        if shutdown_event:
            await shutdown_event.wait()
    except Exception as e:
        logging.exception(f"Bot ishga tushish xatosi: {e}")
        if shutdown_event:
            await shutdown_event.wait()


async def cleanup_resources():
    """Performs graceful resource disposal inside the running event loop (Req 4)."""
    logging.info("🛑 Graceful shutdown boshlandi: resurslar to'xtatilmoqda...")
    request_web_server_exit()
    stop_worker()
    if bot and bot.session:
        try:
            await bot.session.close()
            logging.info("✅ Telegram Bot sessiyasi yopildi.")
        except Exception as e:
            logging.warning(f"Bot sessiyasini yopishda xatolik: {e}")
    try:
        from app.core.redis import close_redis

        await close_redis()
    except Exception as e:
        logging.warning(f"Redis ulanishini yopishda xatolik: {e}")
    try:
        await engine.dispose()
        logging.info("✅ Ma'lumotlar bazasi pooli yopildi.")
    except Exception as e:
        logging.warning(f"Database engine dispose xatoligi: {e}")
    logging.info("🏁 GiftHub resurslari to'liq va xavfsiz to'xtatildi.")


async def main(mode: str = "combined", shutdown_event: asyncio.Event = None):
    setup_logger()
    settings.validate_production()
    logging.info(f"🚀 GiftHub Platform ishga tushirilmoqda (Mode: {mode})...")

    # Initialize Database
    await init_db()
    logging.info("✅ Ma'lumotlar bazasi initsializatsiya qilindi.")

    # Pass bot instance to web server
    set_bot(bot)

    # Setup middlewares and handlers
    setup_middlewares(dp)
    handlers.setup(dp)

    logging.info(f"🌐 Web App URL: {config.WEB_APP_URL}")
    logging.info(f"🌐 Admin Panel URL: {config.ADMIN_APP_URL}")

    if shutdown_event is None:
        shutdown_event = asyncio.Event()

    def _sig_handler():
        logging.info("To'xtatish signali qabul qilindi, shutdown boshlandi...")
        request_web_server_exit()
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _sig_handler)
        except (NotImplementedError, AttributeError, ValueError):
            # Windows: add_signal_handler yo'q. Oddiy signal handler'dan asyncio.Event'ni
            # to'g'ridan-to'g'ri o'rnatish loop'ni uyg'otmaydi — call_soon_threadsafe kerak.
            signal.signal(sig, lambda s, f: loop.call_soon_threadsafe(_sig_handler))

    tasks: list[asyncio.Task] = []
    # Cancel qilinmasdan, o'zi to'xtashi kutiladigan vazifalar (web va worker)
    graceful_tasks: list[asyncio.Task] = []
    try:
        if mode == "api":
            logging.info("Starting standalone API server mode...")
            graceful_tasks.append(asyncio.create_task(start_web_server(), name="web"))
        elif mode == "bot":
            logging.info("Starting standalone Bot mode...")
            if settings.TELEGRAM_MODE == "webhook":
                logging.warning(
                    "⚠️ TELEGRAM_MODE=webhook, lekin 'bot' rejimida API server ishga tushmaydi — "
                    "webhook yangilanishlarini alohida 'api' jarayoni qabul qilishi kerak."
                )
            tasks.append(asyncio.create_task(start_bot(shutdown_event=shutdown_event), name="bot"))
        elif mode == "worker":
            logging.info("Starting standalone Worker mode...")
            graceful_tasks.append(asyncio.create_task(run_worker_loop(bot=bot), name="worker"))
        else:  # combined (Default for development)
            logging.info("Starting combined runtime mode (API + Bot + Worker)...")
            graceful_tasks.append(asyncio.create_task(start_web_server(), name="web"))
            tasks.append(asyncio.create_task(start_bot(shutdown_event=shutdown_event), name="bot"))
            graceful_tasks.append(asyncio.create_task(run_worker_loop(bot=bot), name="worker"))

        shutdown_waiter = asyncio.create_task(shutdown_event.wait(), name="shutdown-waiter")
        done, pending = await asyncio.wait(
            tasks + graceful_tasks + [shutdown_waiter], return_when=asyncio.FIRST_COMPLETED
        )

        # Qaysi komponent kutilmaganda to'xtaganini loglash (aks holda xato yutilib ketadi)
        for t in done:
            if t is shutdown_waiter or t.cancelled():
                continue
            exc = t.exception()
            if exc is not None:
                logging.error(f"❌ '{t.get_name()}' komponenti xato bilan to'xtadi", exc_info=exc)
            else:
                logging.warning(f"⚠️ '{t.get_name()}' komponenti tugadi, shutdown boshlanmoqda.")
        shutdown_event.set()

        # Web server va worker'ni cancel qilmasdan to'xtashini so'raymiz: uvicorn lifespan shutdown'ni
        # bajaradi, worker esa joriy siklini (outbox, to'lov, fulfillment) oxirigacha yetkazib chiqadi.
        request_web_server_exit()
        stop_worker()
        still_running = [t for t in graceful_tasks if t in pending]
        if still_running:
            names = ", ".join(t.get_name() for t in still_running)
            logging.info(f"⏳ Graceful to'xtash kutilmoqda ({names}, maks {GRACEFUL_SHUTDOWN_TIMEOUT}s)...")
            finished, _ = await asyncio.wait(still_running, timeout=GRACEFUL_SHUTDOWN_TIMEOUT)
            for t in still_running:
                if t in finished:
                    pending.discard(t)
                    if not t.cancelled() and t.exception() is not None:
                        logging.error(f"'{t.get_name()}' to'xtash paytida xato berdi", exc_info=t.exception())
                else:
                    logging.warning(
                        f"'{t.get_name()}' {GRACEFUL_SHUTDOWN_TIMEOUT}s ichida to'xtamadi, majburan bekor qilinmoqda."
                    )

        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    finally:
        await cleanup_resources()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GiftHub Production Platform")
    parser.add_argument(
        "--mode",
        choices=["combined", "api", "bot", "worker"],
        default="combined",
        help="Runtime mode: combined (all-in-one), api (FastAPI only), bot (Aiogram only), worker (Background jobs only)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(main(mode=args.mode))
    except (KeyboardInterrupt, SystemExit):
        logging.info("GiftHub to'xtatildi.")
