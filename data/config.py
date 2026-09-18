from environs import Env
import os

env = Env()
env.read_env()

BOT_TOKEN = env.str("BOT_TOKEN")
ADMINS = env.list("ADMINS")
IP = env.str("IP")
PORT = env.int("PORT")
TELEGRAM_API_SERVER = env.str("TELEGRAM_API_SERVER")
TELEGRAM_PROXY = env.str("TELEGRAM_PROXY")

WEB_APP_URL = env.str("WEB_APP_URL")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")

ADMIN_APP_URL = env.str("ADMIN_APP_URL")
WEB_HOST = env.str("WEB_HOST")
WEB_PORT = env.int("WEB_PORT")

def get_web_app_url() -> str:
    try:
        fresh_env = Env()
        fresh_env.read_env(ENV_PATH, override=True)
        return fresh_env.str("WEB_APP_URL", WEB_APP_URL)
    except Exception:
        return WEB_APP_URL

def get_admin_app_url() -> str:
    try:
        fresh_env = Env()
        fresh_env.read_env(ENV_PATH, override=True)
        return fresh_env.str("ADMIN_APP_URL", ADMIN_APP_URL)
    except Exception:
        return ADMIN_APP_URL

# Qo'llab-quvvatlash va Kanal sozlamalari
SUPPORT_URL = env.str("SUPPORT_URL")
NEWS_CHANNEL_URL = env.str("NEWS_CHANNEL_URL")

# Database sozlamalari
DB_URL = env.str("DB_URL")

# Click Merchant sozlamalari
CLICK_SERVICE_ID = env.str("CLICK_SERVICE_ID")
CLICK_MERCHANT_ID = env.str("CLICK_MERCHANT_ID")
CLICK_SECRET_KEY = env.str("CLICK_SECRET_KEY")

# Payme Merchant sozlamalari
PAYME_MERCHANT_ID = env.str("PAYME_MERCHANT_ID")
PAYME_SECRET_KEY = env.str("PAYME_SECRET_KEY")

# AutoPayCard sozlamalari
AUTOPAYCARD_API_KEY = env.str("AUTOPAYCARD_API_KEY")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))