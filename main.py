import argparse
import asyncio
import logging
import signal
import socket
import sys
import uvicorn
from aiohttp.resolver import DefaultResolver
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage

from app import handlers
from app.core.config import settings
from app.core.database import engine
from app.core.redis import get_fsm_storage
from app.services.worker import run_worker_loop, stop_worker
from app.utils.misc.logging import setup_logger
from app.utils.notify_admins import notify_admins
from app.utils.set_bot_commands import set_bot_commands
from app.web.server import app as fastapi_app, set_bot
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

bot = Bot(
    token=config.BOT_TOKEN,
    session=bot_session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
storage = get_fsm_storage()
dp = Dispatcher(storage=storage)


async def start_web_server():
    server_config = uvicorn.Config(
        app=fastapi_app,
        host=config.WEB_HOST,
        port=config.WEB_PORT,
        log_level="info"
    )
    server = uvicorn.Server(server_config)
    await server.serve()


async def start_bot():
    try:
        try:
            bot_info = await bot.get_me()
            set_bot(bot, bot_info.username)
            logging.info(f"🤖 Telegram Bot: @{bot_info.username}")
        except Exception as e:
            logging.warning(f"Bot info olishda ogohlantirish: {e}")

        await set_bot_commands(bot)

        # Standart Telegram buyruqlar menyusini o'rnatish
        try:
            from aiogram.types import MenuButtonCommands
            await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
            logging.info("✅ Telegram Chat Menu Button standart buyruqlar menyusiga sozlandi.")
        except Exception as err:
            logging.warning(f"Chat menu button sozlashda ogohlantirish: {err}")

        await notify_admins(bot)

        # Webhook vs Polling Mode (Req 14 & Req 13)
        if settings.TELEGRAM_MODE == "webhook" and settings.TELEGRAM_WEBHOOK_URL:
            webhook_url = f"{settings.TELEGRAM_WEBHOOK_URL.rstrip('/')}/webhook/telegram"
            await bot.set_webhook(
                url=webhook_url,
                secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
                drop_pending_updates=settings.DROP_PENDING_UPDATES
            )
            logging.info(f"✅ Telegram Webhook rejimida ulandi: {webhook_url}")
        else:
            await bot.delete_webhook(drop_pending_updates=settings.DROP_PENDING_UPDATES)
            logging.info(f"✅ Telegram Polling boshlandi (drop_pending_updates={settings.DROP_PENDING_UPDATES})")
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

    except TelegramUnauthorizedError:
        logging.warning("⚠️ BOT_TOKEN yaroqsiz yoki test tokeni kiritilgan. Bot to'xtatildi, lekin API serveri ishlashda davom etadi!")
    except Exception as e:
        logging.error(f"Bot ishga tushish xatosi: {e}")


async def cleanup_resources():
    """Performs graceful resource disposal inside the running event loop (Req 4)."""
    logging.info("🛑 Graceful shutdown boshlandi: resurslar to'xtatilmoqda...")
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


async def main(mode: str = "combined"):
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

    shutdown_event = asyncio.Event()

    def _sig_handler():
        logging.info("To'xtatish signali qabul qilindi, shutdown boshlandi...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _sig_handler)
        except (NotImplementedError, AttributeError):
            # Windows platform compatibility
            signal.signal(sig, lambda s, f: shutdown_event.set())

    tasks = []
    try:
        if mode == "api":
            logging.info("Starting standalone API server mode...")
            tasks.append(asyncio.create_task(start_web_server()))
        elif mode == "bot":
            logging.info("Starting standalone Bot polling mode...")
            tasks.append(asyncio.create_task(start_bot()))
        elif mode == "worker":
            logging.info("Starting standalone Worker mode...")
            tasks.append(asyncio.create_task(run_worker_loop(bot=bot)))
        else: # combined (Default for development)
            logging.info("Starting combined runtime mode (API + Bot + Worker)...")
            tasks.append(asyncio.create_task(start_web_server()))
            tasks.append(asyncio.create_task(start_bot()))
            tasks.append(asyncio.create_task(run_worker_loop(bot=bot)))

        shutdown_waiter = asyncio.create_task(shutdown_event.wait())
        done, pending = await asyncio.wait(
            tasks + [shutdown_waiter],
            return_when=asyncio.FIRST_COMPLETED
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
        help="Runtime mode: combined (all-in-one), api (FastAPI only), bot (Aiogram only), worker (Background jobs only)"
    )
    args = parser.parse_args()

    try:
        asyncio.run(main(mode=args.mode))
    except (KeyboardInterrupt, SystemExit):
        logging.info("GiftHub to'xtatildi.")