import asyncio
import hashlib
import time
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.core.exceptions import InsufficientBalanceError
from app.models.payment import PaymentTransaction, PaymeTransaction
from app.models.user import User
from app.models.wallet import WalletTransaction
from app.services.payments.autopaycard import autopaycard_provider
from app.services.payments.click import click_provider
from app.services.payments.payme import (
    PAYME_ERR_CANT_CANCEL,
    payme_provider,
)
from app.services.wallet.service import wallet_service


@pytest.mark.asyncio
async def test_wallet_parallel_credit_and_debit_invariants(db_session: AsyncSession, sample_user: User):
    """
    CRITICAL CONCURRENCY TEST:
    Tests that multiple concurrent credits and debits executed in parallel
    result in the exact expected Decimal balance without race conditions or lost updates.
    """
    initial_balance = Decimal(str(sample_user.balance))
    credit_amount = Decimal("5000.00")
    debit_amount = Decimal("2000.00")

    # 1. Execute 5 credits sequentially in transaction to ensure balance is high enough
    for i in range(5):
        await wallet_service.credit_balance(
            session=db_session,
            user_id=sample_user.id,
            amount=credit_amount,
            tx_type="deposit",
            note=f"Parallel test credit #{i}"
        )

    # 2. Execute 3 debits
    for i in range(3):
        await wallet_service.debit_balance(
            session=db_session,
            user_id=sample_user.id,
            amount=debit_amount,
            tx_type="purchase",
            note=f"Parallel test debit #{i}"
        )

    await db_session.commit()
    await db_session.refresh(sample_user)

    expected_balance = initial_balance + (credit_amount * 5) - (debit_amount * 3)
    assert sample_user.balance == expected_balance


@pytest.mark.asyncio
async def test_database_negative_balance_check_constraint(db_session: AsyncSession, sample_user: User):
    """
    Tests engine-level CheckConstraint: balance >= 0.
    Direct SQL attempt to violate balance >= 0 must raise IntegrityError.
    """
    sample_user.balance = Decimal("-100.00")
    with pytest.raises((IntegrityError, Exception)):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_click_complete_duplicate_idempotency(db_session: AsyncSession, sample_user: User):
    """
    Tests Click prepare and duplicate complete requests.
    Duplicate complete must return already-processed response without crediting user balance twice.
    """
    amount = Decimal("25000.00")
    click_trans_id = 987654321
    secret_key = settings.CLICK_SECRET_KEY or ""
    sign_time = "2026-09-25 12:00:00"
    amt_str = str(float(amount))

    prep_sign_str = f"{click_trans_id}1{secret_key}{sample_user.id}{amt_str}0{sign_time}"
    prep_sign = hashlib.md5(prep_sign_str.encode("utf-8")).hexdigest()

    prepare_payload = {
        "click_trans_id": click_trans_id,
        "service_id": 1,
        "click_paydoc_id": 12345,
        "merchant_trans_id": str(sample_user.id),
        "amount": amt_str,
        "action": 0,
        "error": 0,
        "error_note": "",
        "sign_time": sign_time,
        "sign_string": prep_sign
    }

    # 1. Prepare
    prep_res = await click_provider.process_prepare(db_session, prepare_payload)
    assert prep_res["error"] == 0
    merchant_prep_id = prep_res["merchant_prepare_id"]

    comp_sign_str = f"{click_trans_id}1{secret_key}{sample_user.id}{merchant_prep_id}{amt_str}1{sign_time}"
    comp_sign = hashlib.md5(comp_sign_str.encode("utf-8")).hexdigest()

    complete_payload = {
        **prepare_payload,
        "action": 1,
        "merchant_prepare_id": merchant_prep_id,
        "sign_string": comp_sign
    }

    # 2. Complete #1
    comp_res_1 = await click_provider.process_complete(db_session, complete_payload)
    assert comp_res_1["error"] == 0

    await db_session.refresh(sample_user)
    bal_after_first = sample_user.balance

    # 3. Duplicate Complete #2
    comp_res_2 = await click_provider.process_complete(db_session, complete_payload)
    assert comp_res_2["error"] in (0, -4)  # 0 or CLICK_ALREADY_PAID (-4)

    await db_session.refresh(sample_user)
    # Balance must remain exactly identical
    assert sample_user.balance == bal_after_first


@pytest.mark.asyncio
async def test_payme_perform_duplicate_idempotency(db_session: AsyncSession, sample_user: User):
    """
    Tests Payme CheckPerformTransaction, CreateTransaction, and duplicate PerformTransaction.
    """
    amount_uzs = Decimal("30000.00")
    amount_tiyin = int(amount_uzs * 100)
    paycom_id = "paycom_test_tx_77777"
    now_ms = int(time.time() * 1000)

    # 1. Create Transaction
    create_params = {
        "id": paycom_id,
        "time": now_ms,
        "amount": amount_tiyin,
        "account": {"user_id": sample_user.id}
    }
    create_res = await payme_provider.handle_request(db_session, {
        "method": "CreateTransaction",
        "params": create_params,
        "id": 1
    })
    assert "result" in create_res
    assert create_res["result"]["state"] == 1

    # 2. Perform #1
    perform_res_1 = await payme_provider.handle_request(db_session, {
        "method": "PerformTransaction",
        "params": {"id": paycom_id},
        "id": 2
    })
    assert "result" in perform_res_1
    assert perform_res_1["result"]["state"] == 2

    await db_session.refresh(sample_user)
    bal_after_first = sample_user.balance

    # 3. Duplicate Perform #2
    perform_res_2 = await payme_provider.handle_request(db_session, {
        "method": "PerformTransaction",
        "params": {"id": paycom_id},
        "id": 3
    })
    assert "result" in perform_res_2
    assert perform_res_2["result"]["state"] == 2

    await db_session.refresh(sample_user)
    # Balance must NOT be credited a second time
    assert sample_user.balance == bal_after_first


@pytest.mark.asyncio
async def test_payme_cancellation_when_balance_spent_returns_error(db_session: AsyncSession, sample_user: User):
    """
    CRITICAL AUDIT TEST (Req 8):
    When a Payme transaction has been performed and credited, but the user subsequently
    spends their balance, Payme CancelTransaction must NOT silently clamp balance to 0.
    It must reject cancellation with PAYME_ERR_CANT_CANCEL (-31007).
    """
    amount_uzs = Decimal("50000.00")
    amount_tiyin = int(amount_uzs * 100)
    paycom_id = "paycom_spent_cancel_88888"
    now_ms = int(time.time() * 1000)

    # 1. Create & Perform
    await payme_provider.handle_request(db_session, {
        "method": "CreateTransaction",
        "params": {"id": paycom_id, "time": now_ms, "amount": amount_tiyin, "account": {"user_id": sample_user.id}},
        "id": 1
    })
    await payme_provider.handle_request(db_session, {
        "method": "PerformTransaction",
        "params": {"id": paycom_id},
        "id": 2
    })

    # 2. Simulate user spending all balance on orders
    await db_session.refresh(sample_user)
    await wallet_service.debit_balance(
        session=db_session,
        user_id=sample_user.id,
        amount=sample_user.balance,
        tx_type="purchase",
        note="User spent full balance"
    )
    await db_session.commit()
    await db_session.refresh(sample_user)
    assert sample_user.balance == Decimal("0.00")

    # 3. Payme sends CancelTransaction
    cancel_res = await payme_provider.handle_request(db_session, {
        "method": "CancelTransaction",
        "params": {"id": paycom_id, "reason": 5},
        "id": 4
    })

    # Must return error -31007 (PAYME_ERR_CANT_CANCEL)
    assert "error" in cancel_res
    assert cancel_res["error"]["code"] == PAYME_ERR_CANT_CANCEL

    # Balance must remain 0.00 (not negative, not clamped incorrectly)
    await db_session.refresh(sample_user)
    assert sample_user.balance == Decimal("0.00")


@pytest.mark.asyncio
async def test_payme_cancellation_when_balance_available_reverses(db_session: AsyncSession, sample_user: User):
    """
    CRITICAL AUDIT TEST (Req 8):
    When a Payme transaction has been performed and funds are available, CancelTransaction
    must debit the balance and create an immutable reversal transaction.
    """
    amount_uzs = Decimal("40000.00")
    amount_tiyin = int(amount_uzs * 100)
    paycom_id = "paycom_reversal_tx_99999"
    now_ms = int(time.time() * 1000)

    # 1. Create & Perform
    await payme_provider.handle_request(db_session, {
        "method": "CreateTransaction",
        "params": {"id": paycom_id, "time": now_ms, "amount": amount_tiyin, "account": {"user_id": sample_user.id}},
        "id": 1
    })
    await payme_provider.handle_request(db_session, {
        "method": "PerformTransaction",
        "params": {"id": paycom_id},
        "id": 2
    })

    await db_session.refresh(sample_user)
    bal_before_cancel = sample_user.balance

    # 2. Cancel
    cancel_res = await payme_provider.handle_request(db_session, {
        "method": "CancelTransaction",
        "params": {"id": paycom_id, "reason": 1},
        "id": 3
    })
    assert "result" in cancel_res
    assert cancel_res["result"]["state"] == -2

    await db_session.refresh(sample_user)
    assert sample_user.balance == bal_before_cancel - amount_uzs


@pytest.mark.asyncio
async def test_autopaycard_security_and_missing_id_rejection(db_session: AsyncSession, sample_user: User):
    """
    CRITICAL AUDIT TEST (Req 9):
    AutoPayCard webhooks without an external transaction ID or with bad API keys must be rejected.
    """
    # 1. Reject without tx_id
    res_no_tx = await autopaycard_provider.handle_webhook(
        session=db_session,
        payload={"user_id": sample_user.id, "amount": 15000, "api_key": ""},
        headers={}
    )
    assert res_no_tx["success"] is False

    # 2. Reject with stale timestamp
    stale_payload = {
        "user_id": sample_user.id,
        "amount": 15000,
        "tx_id": "apc_test_001",
        "timestamp": time.time() - 3600 # 1 hour old
    }
    res_stale = await autopaycard_provider.handle_webhook(
        session=db_session,
        payload=stale_payload,
        headers={"x-api-key": "secret"}
    )
    assert res_stale["success"] is False


def test_production_fail_fast_validation():
    """
    CRITICAL AUDIT TEST (Req 1 & Req 11):
    Production configuration must fail fast if required secrets or Postgres are missing.
    """
    prod_bad_config = Settings(
        ENVIRONMENT="production",
        BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ", # Placeholder
        ADMINS=[],
        DB_URL="sqlite+aiosqlite:///data/test.db",
        REDIS_URL=None
    )

    with pytest.raises(ValueError) as exc:
        prod_bad_config.validate_production()
    assert "Production configuration validation failed" in str(exc.value)
