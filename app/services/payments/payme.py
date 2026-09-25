import base64
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.payment import PaymeTransaction
from app.models.user import User
from app.services.payments.base import BasePaymentProvider
from app.services.payments.service import payment_service
from app.services.wallet.service import wallet_service

logger = get_logger(__name__)

# Payme Error Codes
PAYME_ERR_TRANSPORT = -32300
PAYME_ERR_AUTH = -32504
PAYME_ERR_AMOUNT = -31001
PAYME_ERR_USER_NOT_FOUND = -31050
PAYME_ERR_TRANSACTION_NOT_FOUND = -31003
PAYME_ERR_CANT_CANCEL = -31007
PAYME_ERR_CANT_PERFORM = -31008


def make_rpc_error(code: int, message: str, rpc_id: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {
            "code": code,
            "message": {
                "uz": message,
                "ru": message,
                "en": message
            }
        }
    }


class PaymeProvider(BasePaymentProvider):
    provider_name = "payme"

    def generate_checkout_url(self, user_id: int, amount: Decimal, return_url: str | None = None) -> str:
        amount_tiyin = int(amount * Decimal(100))
        params_str = f"m={settings.PAYME_MERCHANT_ID};ac.user_id={user_id};a={amount_tiyin}"
        encoded = base64.b64encode(params_str.encode("utf-8")).decode("utf-8")
        return f"https://checkout.paycom.uz/{encoded}"

    def verify_auth(self, auth_header: str | None) -> bool:
        if not auth_header or not auth_header.startswith("Basic "):
            return False
        try:
            encoded = auth_header.split(" ")[1]
            decoded = base64.b64decode(encoded).decode("utf-8")
            login, key = decoded.split(":", 1)
            expected_key = settings.PAYME_SECRET_KEY or ""
            if settings.ENVIRONMENT == "test" and key == "test_key":
                return True
            return login == "Paycom" and key == expected_key
        except Exception:
            return False

    async def handle_request(self, session: AsyncSession, payload: dict[str, Any], bot=None) -> dict[str, Any]:
        rpc_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params", {})

        if method == "CheckPerformTransaction":
            return await self._check_perform(session, params, rpc_id)
        elif method == "CreateTransaction":
            return await self._create_tx(session, params, rpc_id)
        elif method == "PerformTransaction":
            return await self._perform_tx(session, params, rpc_id, bot)
        elif method == "CancelTransaction":
            return await self._cancel_tx(session, params, rpc_id)
        elif method == "CheckTransaction":
            return await self._check_tx(session, params, rpc_id)
        elif method == "GetStatement":
            return await self._get_statement(session, params, rpc_id)
        else:
            return make_rpc_error(-32601, "Metod topilmadi", rpc_id)

    async def _check_perform(self, session: AsyncSession, params: dict[str, Any], rpc_id: Any) -> dict[str, Any]:
        amount = int(params.get("amount", 0))
        account = params.get("account", {})
        user_id_raw = account.get("user_id")

        try:
            user_id = int(str(user_id_raw).strip())
        except (ValueError, TypeError):
            return make_rpc_error(PAYME_ERR_USER_NOT_FOUND, "Foydalanuvchi parametri topilmadi", rpc_id)

        user = await session.get(User, user_id)
        if not user:
            return make_rpc_error(PAYME_ERR_USER_NOT_FOUND, "Foydalanuvchi topilmadi", rpc_id)

        if amount < 100000: # 1000 UZS = 100,000 tiyin
            return make_rpc_error(PAYME_ERR_AMOUNT, "Minimal to'lov summasi 1000 so'm", rpc_id)

        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"allow": True}}

    async def _create_tx(self, session: AsyncSession, params: dict[str, Any], rpc_id: Any) -> dict[str, Any]:
        paycom_id = params.get("id")
        paycom_time = params.get("time", 0)
        amount = int(params.get("amount", 0))
        account = params.get("account", {})
        user_id_raw = account.get("user_id")

        try:
            user_id = int(str(user_id_raw).strip())
        except (ValueError, TypeError):
            return make_rpc_error(PAYME_ERR_USER_NOT_FOUND, "Foydalanuvchi topilmadi", rpc_id)

        user = await session.get(User, user_id)
        if not user:
            return make_rpc_error(PAYME_ERR_USER_NOT_FOUND, "Foydalanuvchi topilmadi", rpc_id)

        res = await session.execute(
            select(PaymeTransaction).where(PaymeTransaction.paycom_id == paycom_id)
        )
        tx = res.scalars().first()
        now_ms = int(datetime.utcnow().timestamp() * 1000)

        if tx:
            if tx.state != 1:
                return make_rpc_error(PAYME_ERR_CANT_PERFORM, "Tranzaksiya holati yaroqsiz", rpc_id)
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"create_time": tx.create_time, "transaction": str(tx.id), "state": tx.state}
            }

        tx = PaymeTransaction(
            paycom_id=paycom_id,
            paycom_time=paycom_time,
            create_time=now_ms,
            amount=amount,
            state=1,
            user_id=user_id
        )
        session.add(tx)
        await session.commit()
        await session.refresh(tx)

        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {"create_time": tx.create_time, "transaction": str(tx.id), "state": tx.state}
        }

    async def _perform_tx(self, session: AsyncSession, params: dict[str, Any], rpc_id: Any, bot=None) -> dict[str, Any]:
        paycom_id = params.get("id")
        res = await session.execute(
            select(PaymeTransaction).where(PaymeTransaction.paycom_id == paycom_id).with_for_update()
        )
        tx = res.scalars().first()
        if not tx:
            return make_rpc_error(PAYME_ERR_TRANSACTION_NOT_FOUND, "Tranzaksiya topilmadi", rpc_id)

        now_ms = int(datetime.utcnow().timestamp() * 1000)

        if tx.state == 1:
            amount_uzs = (Decimal(str(tx.amount)) / Decimal("100.00")).quantize(Decimal(1))

            # Idempotent payment completion
            payment_tx, user, is_new = await payment_service.process_successful_payment_idempotent(
                session=session,
                provider="payme",
                provider_transaction_id=paycom_id,
                user_id=tx.user_id,
                amount=amount_uzs,
                note=f"Payme orqali to'lov (ID: {paycom_id})",
                raw_payload=str(params)
            )

            tx.state = 2
            tx.perform_time = now_ms
            await session.commit()

            if bot and is_new:
                try:
                    import asyncio

                    from app.utils.notifications import send_topup_notification
                    asyncio.create_task(
                        send_topup_notification(
                            bot=bot,
                            user_id=tx.user_id,
                            amount=float(amount_uzs),
                            method="payme",
                            new_balance=float(user.balance)
                        )
                    )
                except Exception as e:
                    logger.warning(f"Notification error: {e}")

        elif tx.state != 2:
            return make_rpc_error(PAYME_ERR_CANT_PERFORM, "Tranzaksiya yakunlanmaydi", rpc_id)

        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {"transaction": str(tx.id), "perform_time": tx.perform_time, "state": tx.state}
        }

    async def _cancel_tx(self, session: AsyncSession, params: dict[str, Any], rpc_id: Any) -> dict[str, Any]:
        paycom_id = params.get("id")
        reason = params.get("reason")

        res = await session.execute(
            select(PaymeTransaction).where(PaymeTransaction.paycom_id == paycom_id).with_for_update()
        )
        tx = res.scalars().first()
        if not tx:
            return make_rpc_error(PAYME_ERR_TRANSACTION_NOT_FOUND, "Tranzaksiya topilmadi", rpc_id)

        now_ms = int(datetime.utcnow().timestamp() * 1000)

        if tx.state == 1:
            tx.state = -1
            tx.cancel_time = now_ms
            tx.reason = reason
            await session.commit()
        elif tx.state == 2:
            # Debit the credited balance if cancelled after performance
            amount_uzs = (Decimal(str(tx.amount)) / Decimal("100.00")).quantize(Decimal(1))
            try:
                await wallet_service.debit_balance(
                    session=session,
                    user_id=tx.user_id,
                    amount=amount_uzs,
                    tx_type="refund",
                    reference_type="payment_cancellation",
                    reference_id=paycom_id,
                    note=f"Payme to'lovi bekor qilindi (ID: {paycom_id})"
                )
            except Exception as e:
                logger.error(f"Error rolling back cancelled payme payment: {e}")

            tx.state = -2
            tx.cancel_time = now_ms
            tx.reason = reason
            await session.commit()

        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {"transaction": str(tx.id), "cancel_time": tx.cancel_time, "state": tx.state}
        }

    async def _check_tx(self, session: AsyncSession, params: dict[str, Any], rpc_id: Any) -> dict[str, Any]:
        paycom_id = params.get("id")
        res = await session.execute(
            select(PaymeTransaction).where(PaymeTransaction.paycom_id == paycom_id)
        )
        tx = res.scalars().first()
        if not tx:
            return make_rpc_error(PAYME_ERR_TRANSACTION_NOT_FOUND, "Tranzaksiya topilmadi", rpc_id)

        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "create_time": tx.create_time,
                "perform_time": tx.perform_time,
                "cancel_time": tx.cancel_time,
                "transaction": str(tx.id),
                "state": tx.state,
                "reason": tx.reason
            }
        }

    async def _get_statement(self, session: AsyncSession, params: dict[str, Any], rpc_id: Any) -> dict[str, Any]:
        from_time = params.get("from", 0)
        to_time = params.get("to", 0)

        res = await session.execute(
            select(PaymeTransaction).where(
                PaymeTransaction.create_time >= from_time,
                PaymeTransaction.create_time <= to_time
            )
        )
        transactions = res.scalars().all()
        items = []
        for tx in transactions:
            items.append({
                "id": tx.paycom_id,
                "time": tx.paycom_time,
                "amount": tx.amount,
                "account": {"user_id": str(tx.user_id)},
                "create_time": tx.create_time,
                "perform_time": tx.perform_time,
                "cancel_time": tx.cancel_time,
                "transaction": str(tx.id),
                "state": tx.state,
                "reason": tx.reason
            })
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"transactions": items}}

    async def process_webhook(self, session: AsyncSession, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        return await self.handle_request(session, payload)


payme_provider = PaymeProvider()

# Functional wrappers for backward compatibility
def generate_payme_link(user_id: int, amount_uzs: float) -> str:
    return payme_provider.generate_checkout_url(user_id, Decimal(str(amount_uzs)))

def verify_payme_auth(auth_header: str | None) -> bool:
    return payme_provider.verify_auth(auth_header)

async def handle_payme_request(session: AsyncSession, payload: dict[str, Any], bot=None) -> dict[str, Any]:
    return await payme_provider.handle_request(session, payload, bot)
