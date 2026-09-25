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

    async def handle_webhook(
        self, session: AsyncSession, payload: dict[str, Any], headers: dict[str, str] | None = None, bot=None
    ) -> dict[str, Any]:
        import hmac
        import time

        # 1. Check if active
        payment_setting = await session.get(PaymentSetting, 1)
        if not payment_setting or not payment_setting.autopaycard_active:
            return {"success": False, "detail": "AutoPayCard xizmati faol emas"}

        # 2. Strong Webhook Authentication
        api_key = None
        if headers:
            auth_hdr = headers.get("authorization") or headers.get("Authorization") or ""
            if auth_hdr.startswith("Bearer "):
                api_key = auth_hdr.replace("Bearer ", "").strip()
            elif not api_key:
                api_key = headers.get("x-api-key") or headers.get("X-API-Key")

        if not api_key:
            api_key = payload.get("api_key") or payload.get("secret")

        expected_key = payment_setting.autopaycard_api_key or settings.AUTOPAYCARD_API_KEY
        if not expected_key or not api_key or not hmac.compare_digest(str(api_key).strip(), str(expected_key).strip()):
            logger.warning("[AutoPayCard] Webhook rejected: missing or invalid API key")
            return {"success": False, "detail": "Yaroqsiz yoki ruxsat etilmagan API kalit"}

        # 3. Replay Protection via timestamp if provided
        ts = payload.get("timestamp")
        if ts is not None:
            try:
                ts_float = float(ts)
                # If milliseconds timestamp, convert to seconds
                if ts_float > 1e11:
                    ts_float = ts_float / 1000.0
                now_sec = time.time()
                if abs(now_sec - ts_float) > 600:  # 10 minutes tolerance window
                    logger.warning(f"[AutoPayCard] Webhook rejected: timestamp expired ({ts_float} vs {now_sec})")
                    return {"success": False, "detail": "Vaqt tamg'asi eskirgan (replay protection)"}
            except (ValueError, TypeError):
                pass

        # 4. Mandatory Provider Transaction ID (Hard idempotency invariant)
        provider_tx_id = payload.get("tx_id") or payload.get("transaction_id") or payload.get("id")
        if not provider_tx_id or not str(provider_tx_id).strip():
            logger.warning("[AutoPayCard] Webhook rejected: provider transaction ID missing")
            return {"success": False, "detail": "Tranzaksiya identifikatori (tx_id) talab qilinadi"}

        provider_tx_id = str(provider_tx_id).strip()

        # 5. Extract and validate user and amount
        user_id_raw = payload.get("user_id") or payload.get("comment") or payload.get("note")
        amount_raw = payload.get("amount", 0)

        try:
            amount = Decimal(str(amount_raw))
        except Exception:
            return {"success": False, "detail": "Yaroqsiz summa"}

        if amount < Decimal("1000.00"):
            return {"success": False, "detail": "Minimal summa 1 000 so'm"}

        try:
            user_id = int(str(user_id_raw).strip())
        except (ValueError, TypeError):
            return {"success": False, "detail": "Foydalanuvchi ID topilmadi"}

        user = await session.get(User, user_id)
        if not user:
            return {"success": False, "detail": "Foydalanuvchi topilmadi"}

        card_last4 = payload.get("card_last4") or payment_setting.autopaycard_last4 or "karta"

        # 4. Idempotent payment processing
        payment_tx, updated_user, is_new = await payment_service.process_successful_payment_idempotent(
            session=session,
            provider="autopaycard",
            provider_transaction_id=str(provider_tx_id),
            user_id=user_id,
            amount=amount,
            note=f"AutoPayCard ({card_last4}) orqali to'ldirildi",
            raw_payload=str(payload),
        )

        return {
            "success": True,
            "user_id": user_id,
            "new_balance": round(float(updated_user.balance)),
            "amount": float(amount),
        }

    async def process_webhook(
        self, session: AsyncSession, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return await self.handle_webhook(session, payload, headers=headers)


autopaycard_provider = AutoPayCardProvider()


async def handle_autopaycard_webhook(
    session: AsyncSession, payload: dict[str, Any], headers: dict[str, str] | None = None, bot=None
) -> dict[str, Any]:
    return await autopaycard_provider.handle_webhook(session, payload, headers=headers, bot=bot)
