import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.payment import PaymentSetting
from app.models.user import User
from app.services.payments.base import BasePaymentProvider
from app.services.payments.service import payment_service

logger = get_logger(__name__)


class AutoPayCardProvider(BasePaymentProvider):
    provider_name = "autopaycard"

    def generate_checkout_url(self, user_id: int, amount: Decimal, return_url: str | None = None) -> str:
        return ""

    async def handle_webhook(self, session: AsyncSession, payload: dict[str, Any], bot=None) -> dict[str, Any]:
        # 1. Check if active
        payment_setting = await session.get(PaymentSetting, 1)
        if not payment_setting or not payment_setting.autopaycard_active:
            return {"success": False, "detail": "AutoPayCard xizmati faol emas"}

        # 2. Check API key
        api_key = payload.get("api_key") or payload.get("secret")
        expected_key = payment_setting.autopaycard_api_key or settings.AUTOPAYCARD_API_KEY
        if expected_key and api_key != expected_key:
            return {"success": False, "detail": "Yaroqsiz API kalit"}

        # 3. Extract user, amount, and provider transaction ID
        user_id_raw = payload.get("user_id") or payload.get("comment") or payload.get("note")
        amount_raw = payload.get("amount", 0)
        provider_tx_id = payload.get("tx_id") or payload.get("transaction_id") or payload.get("id")

        try:
            amount = Decimal(str(amount_raw))
        except Exception:
            return {"success": False, "detail": "Yaroqsiz summa"}

        try:
            user_id = int(str(user_id_raw).strip())
        except (ValueError, TypeError):
            return {"success": False, "detail": "Foydalanuvchi ID topilmadi"}

        user = await session.get(User, user_id)
        if not user:
            return {"success": False, "detail": "Foydalanuvchi topilmadi"}

        if amount < Decimal("1000.00"):
            return {"success": False, "detail": "Minimal summa 1 000 so'm"}

        if not provider_tx_id:
            # Generate deterministic fallback ID based on user and timestamp/comment if external ID is missing
            t_stamp = payload.get("timestamp", int(Decimal(str(amount))))
            provider_tx_id = f"apc_{user_id}_{t_stamp}_{uuid.uuid4().hex[:6]}"

        card_last4 = payload.get("card_last4") or payment_setting.autopaycard_last4 or "karta"

        # 4. Idempotent payment processing
        payment_tx, updated_user, is_new = await payment_service.process_successful_payment_idempotent(
            session=session,
            provider="autopaycard",
            provider_transaction_id=str(provider_tx_id),
            user_id=user_id,
            amount=amount,
            note=f"AutoPayCard ({card_last4}) orqali to'ldirildi",
            raw_payload=str(payload)
        )

        if bot and is_new:
            try:
                import asyncio

                from app.utils.notifications import send_topup_notification
                asyncio.create_task(
                    send_topup_notification(
                        bot=bot,
                        user_id=user_id,
                        amount=float(amount),
                        method="autopaycard",
                        new_balance=float(updated_user.balance)
                    )
                )
            except Exception as e:
                logger.warning(f"Notification error: {e}")

        return {
            "success": True,
            "user_id": user_id,
            "new_balance": round(float(updated_user.balance)),
            "amount": float(amount)
        }

    async def process_webhook(self, session: AsyncSession, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        return await self.handle_webhook(session, payload)


autopaycard_provider = AutoPayCardProvider()

async def handle_autopaycard_webhook(session: AsyncSession, payload: dict[str, Any], bot=None) -> dict[str, Any]:
    return await autopaycard_provider.handle_webhook(session, payload, bot)
