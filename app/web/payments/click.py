import hashlib
import logging
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.notifications import send_topup_notification
from data import config
from database import queries
from database.models import ClickTransaction

logger = logging.getLogger(__name__)

# Click Error Codes
CLICK_SUCCESS = 0
CLICK_SIGN_CHECK_FAILED = -1
CLICK_INVALID_AMOUNT = -2
CLICK_ACTION_NOT_FOUND = -3
CLICK_ALREADY_PAID = -4
CLICK_USER_NOT_FOUND = -5
CLICK_TRANSACTION_NOT_FOUND = -6
CLICK_ERROR_FAILED = -8
CLICK_TRANSACTION_CANCELLED = -9

def generate_click_link(user_id: int, amount: float, return_url: str | None = None) -> str:
    params = {
        "service_id": config.CLICK_SERVICE_ID,
        "merchant_id": config.CLICK_MERCHANT_ID,
        "amount": f"{amount:.2f}",
        "transaction_param": str(user_id)
    }
    if return_url:
        params["return_url"] = return_url
    elif config.WEB_APP_URL:
        params["return_url"] = config.WEB_APP_URL

    return f"https://my.click.uz/services/pay?{urlencode(params)}"

def verify_click_signature(data: dict[str, Any]) -> bool:
    click_trans_id = str(data.get("click_trans_id", ""))
    service_id = str(data.get("service_id", ""))
    secret_key = config.CLICK_SECRET_KEY
    merchant_trans_id = str(data.get("merchant_trans_id", ""))
    amount = str(data.get("amount", ""))
    action = str(data.get("action", ""))
    sign_time = str(data.get("sign_time", ""))
    received_sign = str(data.get("sign_string", ""))

    # MD5 hash format: click_trans_id + service_id + SECRET_KEY + merchant_trans_id + amount + action + sign_time
    sign_string = f"{click_trans_id}{service_id}{secret_key}{merchant_trans_id}{amount}{action}{sign_time}"
    expected_sign = hashlib.md5(sign_string.encode("utf-8")).hexdigest()

    # In dev / test mode if secret key is default allow preview
    if secret_key == "click_secret_key" and not received_sign:
        return True

    return expected_sign.lower() == received_sign.lower()

async def process_click_prepare(session: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    click_trans_id = int(data.get("click_trans_id", 0))
    service_id = int(data.get("service_id", 0))
    merchant_trans_id = str(data.get("merchant_trans_id", ""))
    amount = float(data.get("amount", 0))
    sign_time = str(data.get("sign_time", ""))
    sign_string = str(data.get("sign_string", ""))

    # 1. Signature validation
    if not verify_click_signature(data):
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "error": CLICK_SIGN_CHECK_FAILED,
            "error_note": "SIGN CHECK FAILED!"
        }

    # 2. Extract user_id
    try:
        user_id = int(merchant_trans_id.strip())
    except ValueError:
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "error": CLICK_USER_NOT_FOUND,
            "error_note": "Foydalanuvchi parametri yaroqsiz"
        }

    # 3. Check user existence
    user = await queries.get_user_by_id(session, user_id)
    if not user:
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "error": CLICK_USER_NOT_FOUND,
            "error_note": "Foydalanuvchi topilmadi"
        }

    # 4. Check min amount
    if amount < 1000:
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "error": CLICK_INVALID_AMOUNT,
            "error_note": "Minimal to'lov summasi 1000 so'm"
        }

    # 5. Save or find transaction
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

async def process_click_complete(session: AsyncSession, data: dict[str, Any], bot=None) -> dict[str, Any]:
    click_trans_id = int(data.get("click_trans_id", 0))
    merchant_trans_id = str(data.get("merchant_trans_id", ""))
    merchant_prepare_id = int(data.get("merchant_prepare_id", 0))
    error = int(data.get("error", 0))
    amount = float(data.get("amount", 0))

    if not verify_click_signature(data):
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "error": CLICK_SIGN_CHECK_FAILED,
            "error_note": "SIGN CHECK FAILED!"
        }

    # Find prepare transaction
    res = await session.execute(
        select(ClickTransaction).where(ClickTransaction.click_trans_id == click_trans_id)
    )
    tx = res.scalars().first()
    if not tx:
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "error": CLICK_TRANSACTION_NOT_FOUND,
            "error_note": "Tranzaksiya topilmadi"
        }

    if tx.status == "completed":
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_confirm_id": tx.id,
            "error": CLICK_ALREADY_PAID,
            "error_note": "Tranzaksiya allaqachon yakunlangan"
        }

    # If Click reported an error during complete
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

    # Credit user balance
    updated_user = await queries.update_user_balance(
        session=session,
        user_id=tx.user_id,
        amount=tx.amount,
        tx_type="topup",
        method="click",
        note=f"Click orqali to'lov (ID: {click_trans_id})"
    )

    tx.status = "completed"
    tx.action = 1
    await session.commit()

    # Send telegram notification
    if bot:
        import asyncio
        asyncio.create_task(
            send_topup_notification(
                bot=bot,
                user_id=tx.user_id,
                amount=tx.amount,
                method="click",
                new_balance=updated_user.balance
            )
        )

    return {
        "click_trans_id": click_trans_id,
        "merchant_trans_id": merchant_trans_id,
        "merchant_confirm_id": tx.id,
        "error": CLICK_SUCCESS,
        "error_note": "Success"
    }
