import os
from app.core.config import settings

BASE_DIR = settings.BASE_DIR
ENV_PATH = os.path.join(BASE_DIR, ".env")

BOT_TOKEN = settings.BOT_TOKEN
ADMINS = [str(x) for x in settings.ADMINS]
IP = settings.IP
PORT = settings.PORT
TELEGRAM_API_SERVER = settings.TELEGRAM_API_SERVER
TELEGRAM_PROXY = settings.TELEGRAM_PROXY

WEB_APP_URL = settings.WEB_APP_URL
ADMIN_APP_URL = settings.ADMIN_APP_URL
WEB_HOST = settings.WEB_HOST
WEB_PORT = settings.WEB_PORT

DB_URL = settings.DB_URL
REDIS_URL = settings.REDIS_URL

SUPPORT_URL = settings.SUPPORT_URL
NEWS_CHANNEL_URL = settings.NEWS_CHANNEL_URL

CLICK_SERVICE_ID = settings.CLICK_SERVICE_ID
CLICK_MERCHANT_ID = settings.CLICK_MERCHANT_ID
CLICK_SECRET_KEY = settings.CLICK_SECRET_KEY

PAYME_MERCHANT_ID = settings.PAYME_MERCHANT_ID
PAYME_SECRET_KEY = settings.PAYME_SECRET_KEY

AUTOPAYCARD_API_KEY = settings.AUTOPAYCARD_API_KEY


def get_web_app_url() -> str:
    return settings.WEB_APP_URL


def get_admin_app_url() -> str:
    return settings.ADMIN_APP_URL