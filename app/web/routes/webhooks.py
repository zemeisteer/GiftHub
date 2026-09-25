from fastapi import APIRouter, Header, HTTPException, Request

from app.core.config import settings
from app.core.logging import get_logger
from app.web.state import get_bot

logger = get_logger(__name__)

router = APIRouter(tags=["Webhooks"])


@router.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
):
    """
    Receives Telegram updates in production Webhook mode.
    Validated with X-Telegram-Bot-Api-Secret-Token.
    """
    if settings.TELEGRAM_WEBHOOK_SECRET:
        if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
            logger.warning("Unauthorized webhook request with invalid secret token.")
            raise HTTPException(status_code=403, detail="Invalid webhook secret token.")

    update_dict = await request.json()
    bot = get_bot()
    if bot:
        from aiogram.types import Update

        from main import dp

        update_obj = Update(**update_dict)
        await dp.feed_webhook_update(bot, update_obj)
        return {"ok": True}
    return {"ok": False, "error": "Bot instance not initialized"}
