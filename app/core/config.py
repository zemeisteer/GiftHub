import os

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_PATH = os.path.join(BASE_DIR, ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # General
    PROJECT_NAME: str = "GiftHub"
    ENVIRONMENT: str = "development" # development, production, test
    LOG_LEVEL: str = "INFO"
    BASE_DIR: str = BASE_DIR

    # Telegram Bot
    BOT_TOKEN: str = ""
    ADMINS: list[int] = Field(default_factory=list)
    IP: str = "127.0.0.1"
    PORT: int = 8000
    TELEGRAM_API_SERVER: str | None = None
    TELEGRAM_PROXY: str | None = None
    TELEGRAM_MODE: str = "polling" # polling, webhook
    TELEGRAM_WEBHOOK_URL: str | None = None
    TELEGRAM_WEBHOOK_SECRET: str | None = None
    DROP_PENDING_UPDATES: bool = False

    # Web & URLs
    WEB_HOST: str = "0.0.0.0"
    WEB_PORT: int = 8000
    WEB_APP_URL: str = "http://localhost:8000/app"
    ADMIN_APP_URL: str = "http://localhost:8000/admin"
    SUPPORT_URL: str | None = ""
    NEWS_CHANNEL_URL: str | None = ""

    # Database & Redis
    DB_URL: str = "sqlite+aiosqlite:///data/gifthub.db"
    REDIS_URL: str | None = None

    # Payment Gateways - Click
    CLICK_SERVICE_ID: str | None = ""
    CLICK_MERCHANT_ID: str | None = ""
    CLICK_SECRET_KEY: str | None = ""

    # Payment Gateways - Payme
    PAYME_MERCHANT_ID: str | None = ""
    PAYME_SECRET_KEY: str | None = ""

    # Payment Gateways - AutoPayCard
    AUTOPAYCARD_API_KEY: str | None = ""

    # Commerce & Price Lock
    PRICE_LOCK_SECONDS: int = 600 # 10 minutes

    # Security
    INIT_DATA_MAX_AGE_SECONDS: int = 86400 # 24 hours

    # Demo / Seed
    SEED_DEMO_DATA: bool = False

    @field_validator("ADMINS", mode="before")
    @classmethod
    def parse_admins(cls, v: str | int | list[str | int]) -> list[int]:
        if isinstance(v, list):
            return [int(str(x).strip()) for x in v if str(x).strip().isdigit()]
        if isinstance(v, (int, float)):
            return [int(v)]
        if isinstance(v, str):
            res = []
            for part in v.replace(",", " ").split():
                clean = part.strip()
                if clean.isdigit():
                    res.append(int(clean))
            return res
        return []

    @field_validator("DB_URL", mode="after")
    @classmethod
    def normalize_db_url(cls, v: str) -> str:
        if v.startswith("sqlite+aiosqlite:///"):
            rel = v.replace("sqlite+aiosqlite:///", "")
            if not os.path.isabs(rel):
                abs_path = os.path.join(BASE_DIR, rel).replace("\\", "/")
                return f"sqlite+aiosqlite:///{abs_path}"
        return v

    def validate_production(self) -> None:
        """Explicit fail-fast check invoked during application startup."""
        if self.ENVIRONMENT == "production":
            errors = []
            if not self.BOT_TOKEN or "ABCdefGHI" in self.BOT_TOKEN or len(self.BOT_TOKEN) < 20:
                errors.append("BOT_TOKEN must be configured with a valid production Telegram bot token.")
            if not self.ADMINS:
                errors.append("At least one admin ID must be configured in ADMINS for production.")
            if "sqlite" in self.DB_URL.lower():
                errors.append("PostgreSQL (DB_URL) is strictly required for production; SQLite is not allowed.")
            if not self.REDIS_URL:
                errors.append("REDIS_URL is strictly required for production state and distributed locking.")
            if errors:
                raise ValueError("Production configuration validation failed:\n - " + "\n - ".join(errors))


settings = Settings()

# Backward compatibility functions
def get_web_app_url() -> str:
    return settings.WEB_APP_URL

def get_admin_app_url() -> str:
    return settings.ADMIN_APP_URL
