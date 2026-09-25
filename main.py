import asyncio
import logging
import socket

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp.resolver import DefaultResolver

from app import handlers
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
            except Exception:
                pass
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

from app.core.redis import get_fsm_storage
from app.services.worker import run_worker_loop

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
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except TelegramUnauthorizedError:
        logging.warning("⚠️ BOT_TOKEN yaroqsiz yoki test tokeni kiritilgan. Bot polling to'xtatildi, lekin API serveri ishlashda davom etadi!")
    except Exception as e:
        logging.error(f"Bot polling xatosi: {e}")

async def main():
    setup_logger()
    logging.info("🚀 GiftHub Platform ishga tushirilmoqda...")

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

    # Concurrently run Web App, Telegram Bot polling, and background worker
    await asyncio.gather(
        start_web_server(),
        start_bot(),
        run_worker_loop(bot=bot)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        try:
            asyncio.run(bot.session.close())
        except Exception:
            pass