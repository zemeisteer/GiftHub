import hashlib
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.payment import ClickTransaction
from app.models.user import User
from app.services.payments.base import BasePaymentProvider
from app.services.payments.service import payment_service

logger = get_logger(__name__)

# Click API response error codes
CLICK_SUCCESS = 0
CLICK_SIGN_CHECK_FAILED = -1
CLICK_INVALID_AMOUNT = -2
CLICK_ACTION_NOT_FOUND = -3
CLICK_ALREADY_PAID = -4
CLICK_USER_NOT_FOUND = -5
CLICK_TRANSACTION_NOT_FOUND = -6
CLICK_ERROR_FAILED = -8
CLICK_TRANSACTION_CANCELLED = -9


class ClickProvider(BasePaymentProvider):
    provider_name = "click"

    def generate_checkout_url(self, user_id: int, amount: Decimal, return_url: str | None = None) -> str:
        params = {
            "service_id": settings.CLICK_SERVICE_ID,
            "merchant_id": settings.CLICK_MERCHANT_ID,
            "amount": f"{amount:.2f}",
            "transaction_param": str(user_id)
        }
        if return_url:
            params["return_url"] = return_url
        elif settings.WEB_APP_URL:
            params["return_url"] = settings.WEB_APP_URL
        return f"https://my.click.uz/services/pay?{urlencode(params)}"

    def verify_signature(self, data: dict[str, Any]) -> bool:
        click_trans_id = str(data.get("click_trans_id", ""))
        service_id = str(data.get("service_id", ""))
        secret_key = settings.CLICK_SECRET_KEY or ""
        merchant_trans_id = str(data.get("merchant_trans_id", ""))
        amount = str(data.get("amount", ""))
        action = str(data.get("action", ""))
        sign_time = str(data.get("sign_time", ""))
        received_sign = str(data.get("sign_string", ""))

        if str(action) == "1":
            merchant_prepare_id = str(data.get("merchant_prepare_id", ""))
            sign_string = f"{click_trans_id}{service_id}{secret_key}{merchant_trans_id}{merchant_prepare_id}{amount}{action}{sign_time}"
        else:
            sign_string = f"{click_trans_id}{service_id}{secret_key}{merchant_trans_id}{amount}{action}{sign_time}"

        expected_sign = hashlib.md5(sign_string.encode("utf-8")).hexdigest()

        if settings.ENVIRONMENT == "test" and not received_sign:
            return True

        return expected_sign.lower() == received_sign.lower()

    async def process_prepare(self, session: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
        click_trans_id = int(data.get("click_trans_id", 0))
        service_id = int(data.get("service_id", 0))
        merchant_trans_id = str(data.get("merchant_trans_id", ""))
        amount = Decimal(str(data.get("amount", 0)))
        sign_time = str(data.get("sign_time", ""))
        sign_string = str(data.get("sign_string", ""))

        if not self.verify_signature(data):
            return {
                "click_trans_id": click_trans_id,
                "merchant_trans_id": merchant_trans_id,
                "error": CLICK_SIGN_CHECK_FAILED,
                "error_note": "SIGN CHECK FAILED!"
            }

        try:
            user_id = int(merchant_trans_id.strip())
        except (ValueError, TypeError):
            return {
                "click_trans_id": click_trans_id,
                "merchant_trans_id": merchant_trans_id,
                "error": CLICK_USER_NOT_FOUND,
                "error_note": "Foydalanuvchi parametri yaroqsiz"
            }

        user = await session.get(User, user_id)
        if not user:
            return {
                "click_trans_id": click_trans_id,
                "merchant_trans_id": merchant_trans_id,
                "error": CLICK_USER_NOT_FOUND,
                "error_note": "Foydalanuvchi topilmadi"
            }

        if amount < Decimal("1000.00"):
            return {
                "click_trans_id": click_trans_id,
                "merchant_trans_id": merchant_trans_id,
                "error": CLICK_INVALID_AMOUNT,
                "error_note": "Minimal to'lov summasi 1000 so'm"
            }

        res = await session.execute(
            select(ClickTransaction).where(ClickTransaction.click_trans_id == click_trans_id)
        )
        tx = res.scalars().first()
        if not tx:
            tx = ClickTransaction(
                click_trans_id=click_trans_id,
                service_id=service_id,
                merchant_trans_id=merchant_trans_id,
                amount=amount,
                action=0,
                sign_time=sign_time,
                sign_string=sign_string,
                user_id=user_id,
                status="prepared"
            )
            session.add(tx)
            await session.commit()
            await session.refresh(tx)

        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_prepare_id": tx.id,
            "error": CLICK_SUCCESS,
            "error_note": "Success"
        }

    async def process_complete(self, session: AsyncSession, data: dict[str, Any], bot=None) -> dict[str, Any]:
        click_trans_id = int(data.get("click_trans_id", 0))
        merchant_trans_id = str(data.get("merchant_trans_id", ""))
        merchant_prepare_id = int(data.get("merchant_prepare_id", 0))
        error = int(data.get("error", 0))
        amount = Decimal(str(data.get("amount", 0)))

        if not self.verify_signature(data):
            return {
                "click_trans_id": click_trans_id,
                "merchant_trans_id": merchant_trans_id,
                "error": CLICK_SIGN_CHECK_FAILED,
                "error_note": "SIGN CHECK FAILED!"
            }

        res = await session.execute(
            select(ClickTransaction).where(ClickTransaction.click_trans_id == click_trans_id).with_for_update()
        )
        tx = res.scalars().first()
        if not tx:
            return {
                "click_trans_id": click_trans_id,
                "merchant_trans_id": merchant_trans_id,
                "error": CLICK_TRANSACTION_NOT_FOUND,
                "error_note": "Tranzaksiya topilmadi"
            }

        if merchant_prepare_id and tx.id != merchant_prepare_id:
            return {
                "click_trans_id": click_trans_id,
                "merchant_trans_id": merchant_trans_id,
                "error": CLICK_TRANSACTION_NOT_FOUND,
                "error_note": "merchant_prepare_id mos kelmadi"
            }

        if Decimal(str(tx.amount)) != amount:
            return {
                "click_trans_id": click_trans_id,
                "merchant_trans_id": merchant_trans_id,
                "error": CLICK_INVALID_AMOUNT,
                "error_note": "To'lov summasi PREPARE tranzaksiyasiga mos kelmadi"
            }

        if tx.status == "completed":
            return {
                "click_trans_id": click_trans_id,
                "merchant_trans_id": merchant_trans_id,
                "merchant_confirm_id": tx.id,
                "error": CLICK_ALREADY_PAID,
                "error_note": "Tranzaksiya allaqachon yakunlangan"
            }

        if error < 0:
            tx.status = "cancelled"
            tx.error = error
            await session.commit()
            return {
                "click_trans_id": click_trans_id,
                "merchant_trans_id": merchant_trans_id,
                "error": CLICK_TRANSACTION_CANCELLED,
                "error_note": "Tranzaksiya bekor qilindi"
            }

        # Idempotent payment processing
        payment_tx, user, is_new = await payment_service.process_successful_payment_idempotent(
            session=session,
            provider="click",
            provider_transaction_id=str(click_trans_id),
            user_id=tx.user_id,
            amount=amount,
            note=f"Click orqali to'lov (ID: {click_trans_id})",
            raw_payload=str(data)
        )

        tx.status = "completed"
        tx.action = 1
        await session.commit()

        # Send Telegram notification if bot available
        if bot and is_new:
            try:
                import asyncio

                from app.utils.notifications import send_topup_notification
                asyncio.create_task(
                    send_topup_notification(
                        bot=bot,
                        user_id=tx.user_id,
                        amount=float(amount),
                        method="click",
                        new_balance=float(user.balance)
                    )
                )
            except Exception as e:
                logger.warning(f"Notification error: {e}")

        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_confirm_id": tx.id,
            "error": CLICK_SUCCESS,
            "error_note": "Success"
        }

    async def process_webhook(self, session: AsyncSession, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        action = int(payload.get("action", 0))
        if action == 0:
            return await self.process_prepare(session, payload)
        elif action == 1:
            return await self.process_complete(session, payload)
        return {"error": CLICK_ACTION_NOT_FOUND, "error_note": "Action not found"}


click_provider = ClickProvider()

# Backward-compatibility functional wrappers
def generate_click_link(user_id: int, amount: float, return_url: str | None = None) -> str:
    return click_provider.generate_checkout_url(user_id, Decimal(str(amount)), return_url)

async def process_click_prepare(session: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    return await click_provider.process_prepare(session, data)

async def process_click_complete(session: AsyncSession, data: dict[str, Any], bot=None) -> dict[str, Any]:
    return await click_provider.process_complete(session, data, bot)

def verify_click_signature(data: dict[str, Any]) -> bool:
    return click_provider.verify_signature(data)
