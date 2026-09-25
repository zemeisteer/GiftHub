import base64
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.notifications import send_topup_notification
from data import config
from database import queries
from database.models import PaymeTransaction

logger = logging.getLogger(__name__)

# Payme Error Codes
PAYME_ERR_TRANSPORT = -32300
PAYME_ERR_AUTH = -32504
PAYME_ERR_AMOUNT = -31001
PAYME_ERR_USER_NOT_FOUND = -31050
PAYME_ERR_TRANSACTION_NOT_FOUND = -31003
PAYME_ERR_CANT_CANCEL = -31007
PAYME_ERR_CANT_PERFORM = -31008

def generate_payme_link(user_id: int, amount_uzs: float) -> str:
    amount_tiyin = int(amount_uzs * 100)
    params_str = f"m={config.PAYME_MERCHANT_ID};ac.user_id={user_id};a={amount_tiyin}"
    encoded = base64.b64encode(params_str.encode("utf-8")).decode("utf-8")
    return f"https://checkout.paycom.uz/{encoded}"

def verify_payme_auth(auth_header: str | None) -> bool:
    if not auth_header or not auth_header.startswith("Basic "):
        return False
    try:
        encoded = auth_header.split(" ")[1]
        decoded = base64.b64decode(encoded).decode("utf-8")
        login, key = decoded.split(":", 1)
        # Payme login is always "Paycom"
        expected_key = config.PAYME_SECRET_KEY
        # In test mode allow if key matches or if default test key
        if expected_key == "payme_secret_key":
            return True
        return login == "Paycom" and key == expected_key
    except Exception:
        return False

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

async def handle_payme_request(
    session: AsyncSession,
    payload: dict[str, Any],
    bot=None
) -> dict[str, Any]:
    rpc_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params", {})

    if method == "CheckPerformTransaction":
        return await check_perform_transaction(session, params, rpc_id)
    elif method == "CreateTransaction":
        return await create_transaction(session, params, rpc_id)
    elif method == "PerformTransaction":
        return await perform_transaction(session, params, rpc_id, bot)
    elif method == "CancelTransaction":
        return await cancel_transaction(session, params, rpc_id)
    elif method == "CheckTransaction":
        return await check_transaction(session, params, rpc_id)
    elif method == "GetStatement":
        return await get_statement(session, params, rpc_id)
    else:
        return make_rpc_error(-32601, "Metod topilmadi", rpc_id)

async def check_perform_transaction(session: AsyncSession, params: dict[str, Any], rpc_id: Any) -> dict[str, Any]:
    amount = params.get("amount", 0) # in tiyin
    account = params.get("account", {})
    user_id_raw = account.get("user_id")

    try:
        user_id = int(str(user_id_raw).strip())
    except (ValueError, TypeError):
        return make_rpc_error(PAYME_ERR_USER_NOT_FOUND, "Foydalanuvchi parametri topilmadi", rpc_id)

    user = await queries.get_user_by_id(session, user_id)
    if not user:
        return make_rpc_error(PAYME_ERR_USER_NOT_FOUND, "Foydalanuvchi topilmadi", rpc_id)

    if amount < 100000: # 1000 so'm = 100,000 tiyin
        return make_rpc_error(PAYME_ERR_AMOUNT, "Minimal to'lov summasi 1000 so'm", rpc_id)

    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "allow": True
        }
    }

async def create_transaction(session: AsyncSession, params: dict[str, Any], rpc_id: Any) -> dict[str, Any]:
    paycom_id = params.get("id")
    paycom_time = params.get("time", 0)
    amount = params.get("amount", 0)
    account = params.get("account", {})
    user_id_raw = account.get("user_id")

    try:
        user_id = int(str(user_id_raw).strip())
    except (ValueError, TypeError):
        return make_rpc_error(PAYME_ERR_USER_NOT_FOUND, "Foydalanuvchi topilmadi", rpc_id)

    user = await queries.get_user_by_id(session, user_id)
    if not user:
        return make_rpc_error(PAYME_ERR_USER_NOT_FOUND, "Foydalanuvchi topilmadi", rpc_id)

    # Check if transaction already exists
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
            "result": {
                "create_time": tx.create_time,
                "transaction": str(tx.id),
                "state": tx.state
            }
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
        "result": {
            "create_time": tx.create_time,
            "transaction": str(tx.id),
            "state": tx.state
        }
    }

async def perform_transaction(session: AsyncSession, params: dict[str, Any], rpc_id: Any, bot=None) -> dict[str, Any]:
    paycom_id = params.get("id")

    res = await session.execute(
        select(PaymeTransaction).where(PaymeTransaction.paycom_id == paycom_id)
    )
    tx = res.scalars().first()

    if not tx:
        return make_rpc_error(PAYME_ERR_TRANSACTION_NOT_FOUND, "Tranzaksiya topilmadi", rpc_id)

    now_ms = int(datetime.utcnow().timestamp() * 1000)

    if tx.state == 1:
        # Credit user balance (amount in tiyin -> convert to UZS)
        amount_uzs = tx.amount / 100.0
        updated_user = await queries.update_user_balance(
            session=session,
            user_id=tx.user_id,
            amount=amount_uzs,
            tx_type="topup",
            method="payme",
            note=f"Payme orqali to'lov (ID: {paycom_id})"
        )

        tx.state = 2
        tx.perform_time = now_ms
        await session.commit()

        if bot:
            import asyncio
            asyncio.create_task(
                send_topup_notification(
                    bot=bot,
                    user_id=tx.user_id,
                    amount=amount_uzs,
                    method="payme",
                    new_balance=updated_user.balance
                )
            )

    elif tx.state != 2:
        return make_rpc_error(PAYME_ERR_CANT_PERFORM, "Tranzaksiya yakunlanmaydi", rpc_id)

    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "transaction": str(tx.id),
            "perform_time": tx.perform_time,
            "state": tx.state
        }
    }

async def cancel_transaction(session: AsyncSession, params: dict[str, Any], rpc_id: Any) -> dict[str, Any]:
    paycom_id = params.get("id")
    reason = params.get("reason")

    res = await session.execute(
        select(PaymeTransaction).where(PaymeTransaction.paycom_id == paycom_id)
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
        # Rollback balance if already credited
        amount_uzs = tx.amount / 100.0
        user = await queries.get_user_by_id(session, tx.user_id)
        if user:
            user.balance = max(0.0, user.balance - amount_uzs)
        tx.state = -2
        tx.cancel_time = now_ms
        tx.reason = reason
        await session.commit()

    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "transaction": str(tx.id),
            "cancel_time": tx.cancel_time,
            "state": tx.state
        }
    }

async def check_transaction(session: AsyncSession, params: dict[str, Any], rpc_id: Any) -> dict[str, Any]:
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

async def get_statement(session: AsyncSession, params: dict[str, Any], rpc_id: Any) -> dict[str, Any]:
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

    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "transactions": items
        }
    }
