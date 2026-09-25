import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.notifications import send_topup_notification
from data import config
from database import queries
from database.models import PaymentSetting

logger = logging.getLogger(__name__)

async def handle_autopaycard_webhook(
    session: AsyncSession,
    payload: dict[str, Any],
    bot=None
) -> dict[str, Any]:
    # 1. Check if AutoPayCard is active
    payment_setting = await session.get(PaymentSetting, 1)
    if not payment_setting or not payment_setting.autopaycard_active:
        return {"success": False, "detail": "AutoPayCard xizmati faol emas"}

    # 2. Check API key if set
    api_key = payload.get("api_key") or payload.get("secret")
    expected_key = payment_setting.autopaycard_api_key or config.AUTOPAYCARD_API_KEY
    if expected_key and api_key != expected_key:
        return {"success": False, "detail": "Yaroqsiz API kalit"}

    # 3. Extract user and amount
    user_id_raw = payload.get("user_id") or payload.get("comment") or payload.get("note")
    amount = float(payload.get("amount", 0))

    try:
        user_id = int(str(user_id_raw).strip())
    except (ValueError, TypeError):
        return {"success": False, "detail": "Foydalanuvchi ID topilmadi"}

    user = await queries.get_user_by_id(session, user_id)
    if not user:
        return {"success": False, "detail": "Foydalanuvchi topilmadi"}

    if amount < 1000:
        return {"success": False, "detail": "Minimal summa 1 000 so'm"}

    # 4. Credit balance
    card_last4 = payload.get("card_last4") or payment_setting.autopaycard_last4 or "karta"
    updated_user = await queries.update_user_balance(
        session=session,
        user_id=user_id,
        amount=amount,
        tx_type="topup",
        method="autopaycard",
        note=f"AutoPayCard ({card_last4}) orqali to'ldirildi"
    )

    # 5. Notify user
    if bot:
        import asyncio
        asyncio.create_task(
            send_topup_notification(
                bot=bot,
                user_id=user_id,
                amount=amount,
                method="autopaycard",
                new_balance=updated_user.balance
            )
        )

    return {
        "success": True,
        "user_id": user_id,
        "new_balance": round(updated_user.balance),
        "amount": amount
    }
