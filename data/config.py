from environs import Env
import os

env = Env()
env.read_env()

BOT_TOKEN = env.str("BOT_TOKEN", default="")
ADMINS = env.list("ADMINS", default=[])
IP = env.str("IP", default="127.0.0.1")
PORT = env.int("PORT", default=8000)

WEB_APP_URL = env.str("WEB_APP_URL", default="http://localhost:8000/app")
ADMIN_APP_URL = env.str("ADMIN_APP_URL", default="http://localhost:8000/admin")
WEB_HOST = env.str("WEB_HOST", default="0.0.0.0")
WEB_PORT = env.int("WEB_PORT", default=8000)

# Qo'llab-quvvatlash va Kanal sozlamalari (Ixtiyoriy)
SUPPORT_URL = env.str("SUPPORT_URL", default="")
NEWS_CHANNEL_URL = env.str("NEWS_CHANNEL_URL", default="")

# PostgreSQL Database sozlamalari
DB_USER = env.str("DB_USER", default="postgres")
DB_PASS = env.str("DB_PASS", default="1234")
DB_HOST = env.str("DB_HOST", default="localhost")
DB_PORT = env.int("DB_PORT", default=5432)
DB_NAME = env.str("DB_NAME", default="stellar_db")

default_pg_url = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
DB_URL = env.str("DB_URL", default=default_pg_url)

# Click Merchant sozlamalari
CLICK_SERVICE_ID = env.str("CLICK_SERVICE_ID", default="12345")
CLICK_MERCHANT_ID = env.str("CLICK_MERCHANT_ID", default="12345")
CLICK_SECRET_KEY = env.str("CLICK_SECRET_KEY", default="click_secret_key")

# Payme Merchant sozlamalari
PAYME_MERCHANT_ID = env.str("PAYME_MERCHANT_ID", default="600000000000000000000000")
PAYME_SECRET_KEY = env.str("PAYME_SECRET_KEY", default="payme_secret_key")

# AutoPayCard sozlamalari
AUTOPAYCARD_API_KEY = env.str("AUTOPAYCARD_API_KEY", default="")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))