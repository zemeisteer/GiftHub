from typing import Any

from app.core.config import settings
from app.core.security import validate_telegram_init_data


def validate_init_data(init_data: str, bot_token: str | None = None) -> dict[str, Any] | None:
    """
    Validates Telegram Web App initData string using official HMAC-SHA256
    and validates token age to prevent replay attacks.
    """
    token = bot_token or settings.BOT_TOKEN
    return validate_telegram_init_data(init_data, token)
