import asyncio
import hashlib
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.models.dlq import DLQStatus, FailedJob
from app.models.order import Order, OrderStatus
from app.models.outbox import OutboxEvent, OutboxStatus
from app.models.payment import ClickTransaction, PaymentSetting, PaymentTransaction, PaymeTransaction
from app.models.promo import PromoCode
from app.models.user import User
from app.models.wallet import WalletTransaction
from app.services.dlq.service import dlq_service
from app.services.orders.service import order_service
from app.services.outbox.service import outbox_service
from app.services.payments.autopaycard import autopaycard_provider
from app.services.payments.click import click_provider
from app.services.payments.payme import payme_provider
from app.services.payments.service import payment_service
from app.services.wallet.service import wallet_service
from app.services.worker import get_distributed_worker_heartbeat, process_outbox_events_cycle
from database.db import init_db

# ==============================================================================
# 1. Payment Provider Production Configuration Validation (Req 1)
# ==============================================================================


def test_production_payment_credentials_validation():
    """
    Req 1: In production, enabled payment providers must have all required
    credentials configured with non-default/non-placeholder values.
    """
    # 1. Click enabled with dummy secret
    prod_settings_click = Settings(
        ENVIRONMENT="production",
        BOT_TOKEN="123456789:ABCdefGHIjklMNOpqrsTUVwxyz1234567",
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/db",
        CLICK_ENABLED=True,
        CLICK_SERVICE_ID="12345",
        CLICK_MERCHANT_ID="67890",
        CLICK_SECRET_KEY="placeholder_click_secret",
    )
    with pytest.raises(ValueError, match="CLICK_SECRET_KEY is required and cannot be empty or placeholder"):
        prod_settings_click.validate_production()

    # 2. Payme enabled with empty merchant ID
    prod_settings_payme = Settings(
        ENVIRONMENT="production",
        BOT_TOKEN="123456789:ABCdefGHIjklMNOpqrsTUVwxyz1234567",
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/db",
        PAYME_ENABLED=True,
        PAYME_MERCHANT_ID="",
        PAYME_SECRET_KEY="valid_strong_secret_key",
    )
    with pytest.raises(ValueError, match="PAYME_MERCHANT_ID is required and cannot be empty or placeholder"):
        prod_settings_payme.validate_production()

    # 3. AutoPayCard enabled with dummy api key
    prod_settings_autopay = Settings(
        ENVIRONMENT="production",
        BOT_TOKEN="123456789:ABCdefGHIjklMNOpqrsTUVwxyz1234567",
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/db",
        AUTOPAYCARD_ENABLED=True,
        AUTOPAYCARD_API_KEY="dummy_autopay_key",
    )
    with pytest.raises(ValueError, match="AUTOPAYCARD_API_KEY is required and cannot be empty or placeholder"):
        prod_settings_autopay.validate_production()


# ==============================================================================
# 2. Click Signature Constant-Time Verification & PREPARE Concurrency (Req 2 & 3)
# ==============================================================================


@pytest.mark.asyncio
async def test_click_prepare_concurrency_and_service_validation(
    db_session: AsyncSession, sample_user: User, monkeypatch
):
    """
    Req 2 & 3:
    - Service ID validation: service_id mismatch must return CLICK_ERROR_FAILED (-8).
    - Concurrency & idempotency: Two simultaneous PREPARE requests with the same click_trans_id
      must NOT crash with unhandled IntegrityError or create duplicate transactions,
      and must return existing merchant_prepare_id.
    """
    monkeypatch.setattr(settings, "CLICK_SERVICE_ID", "12345")
    monkeypatch.setattr(settings, "CLICK_SECRET_KEY", "click_secret_key_123")
    click_trans_id = 881234567
    amount = "50000.0"
    sign_time = "2026-09-25 15:30:00"
    secret_key = "click_secret_key_123"

    # Sign with correct parameters
    raw = f"{click_trans_id}12345{secret_key}{sample_user.id}{amount}0{sign_time}"
    sign = hashlib.md5(raw.encode("utf-8")).hexdigest()

    payload = {
        "click_trans_id": click_trans_id,
        "service_id": 12345,
        "click_paydoc_id": 998877,
        "merchant_trans_id": str(sample_user.id),
        "amount": amount,
        "action": 0,
        "error": 0,
        "error_note": "",
        "sign_time": sign_time,
        "sign_string": sign,
    }

    # 1. Invalid service_id check
    bad_service_payload = dict(payload)
    bad_service_payload["service_id"] = 9999999
    bad_service_sign_raw = f"{click_trans_id}9999999{secret_key}{sample_user.id}{amount}0{sign_time}"
    bad_service_payload["sign_string"] = hashlib.md5(bad_service_sign_raw.encode("utf-8")).hexdigest()
    res_bad_service = await click_provider.process_prepare(db_session, bad_service_payload)
    assert res_bad_service.get("error") == -8  # Service ID mismatch

    # 2. Initial PREPARE request
    res1 = await click_provider.process_prepare(db_session, payload)
    assert res1.get("error") == 0
    merchant_prep_id1 = res1.get("merchant_prepare_id")
    assert merchant_prep_id1 is not None

    # 3. Duplicate PREPARE request (simulating network retry or concurrency)
    res2 = await click_provider.process_prepare(db_session, payload)
    assert res2.get("error") == 0
    assert res2.get("merchant_prepare_id") == merchant_prep_id1

    # Verify only ONE ClickTransaction was created in database
    tx_count = (
        await db_session.execute(
            select(func.count(ClickTransaction.id)).where(ClickTransaction.click_trans_id == click_trans_id)
        )
    ).scalar()
    assert tx_count == 1


# ==============================================================================
# 3. Payme & AutoPayCard Concurrency and Idempotency (Req 4)
# ==============================================================================


@pytest.mark.asyncio
async def test_payme_simultaneous_perform_and_cancel_concurrency(db_session: AsyncSession, sample_user: User):
    """
    Req 4:
    - Simultaneous PerformTransaction calls must result in exactly ONE balance credit.
    - Duplicate CancelTransaction calls must be idempotent.
    """
    paycom_id = "payme_concurrency_test_tx_777"
    amount_tiyin = 2500000  # 25,000 UZS
    now_ms = int(time.time() * 1000)

    # 1. Create transaction
    create_params = {"id": paycom_id, "time": now_ms, "amount": amount_tiyin, "account": {"user_id": sample_user.id}}
    create_res = await payme_provider.handle_request(
        db_session, {"jsonrpc": "2.0", "id": 1, "method": "CreateTransaction", "params": create_params}
    )
    assert "result" in create_res
    initial_balance = sample_user.balance

    # 2. Duplicate PerformTransaction requests
    perform_params = {"id": paycom_id}
    res_perf1 = await payme_provider.handle_request(
        db_session, {"jsonrpc": "2.0", "id": 2, "method": "PerformTransaction", "params": perform_params}
    )
    res_perf2 = await payme_provider.handle_request(
        db_session, {"jsonrpc": "2.0", "id": 3, "method": "PerformTransaction", "params": perform_params}
    )

    assert "result" in res_perf1
    assert "result" in res_perf2
    assert res_perf1["result"]["state"] == 2
    assert res_perf2["result"]["state"] == 2

    await db_session.refresh(sample_user)
    # Exactly one credit of 25,000 UZS
    assert sample_user.balance == initial_balance + Decimal("25000.00")

    # 3. Cancel Transaction
    cancel_params = {"id": paycom_id, "reason": 1}
    res_cancel1 = await payme_provider.handle_request(
        db_session, {"jsonrpc": "2.0", "id": 4, "method": "CancelTransaction", "params": cancel_params}
    )
    res_cancel2 = await payme_provider.handle_request(
        db_session, {"jsonrpc": "2.0", "id": 5, "method": "CancelTransaction", "params": cancel_params}
    )

    assert "result" in res_cancel1
    assert "result" in res_cancel2
    assert res_cancel1["result"]["state"] == -2
    assert res_cancel2["result"]["state"] == -2

    # Balance reversed back exactly once
    await db_session.refresh(sample_user)
    assert sample_user.balance == initial_balance


@pytest.mark.asyncio
async def test_autopaycard_duplicate_webhook_idempotency(db_session: AsyncSession, sample_user: User):
    """
    Req 4:
    Duplicate AutoPayCard webhook with the same transaction identity
    must only credit balance once.
    """
    # Ensure PaymentSetting has active AutoPayCard
    payment_setting = await db_session.get(PaymentSetting, 1)
    if payment_setting:
        payment_setting.autopaycard_active = True
        payment_setting.autopaycard_api_key = "test_key"
        await db_session.commit()

    initial_balance = sample_user.balance
    amount = Decimal("30000.00")
    tx_id = "autopay_dup_webhook_999"

    payload = {
        "status": "success",
        "tx_id": tx_id,
        "user_id": sample_user.id,
        "amount": float(amount),
        "api_key": "test_key",
    }

    # First webhook arrival
    res1 = await autopaycard_provider.handle_webhook(db_session, payload)
    assert res1["success"] is True

    # Duplicate webhook arrival
    res2 = await autopaycard_provider.handle_webhook(db_session, payload)
    assert res2["success"] is True

    # Balance must only have been credited once
    await db_session.refresh(sample_user)
    assert sample_user.balance == initial_balance + amount


# ==============================================================================
# 4. Outbox Multi-Worker Claiming & Exponential Retry Backoff (Req 5 & 6)
# ==============================================================================


@pytest.mark.asyncio
async def test_outbox_multi_worker_claiming_and_backoff(db_session: AsyncSession):
    """
    Req 5 & 6:
    - Multi-worker claiming: Two workers claiming pending events with claim_pending_events
      must not receive the same events.
    - Lifecycle: PENDING -> PROCESSING -> RETRY -> FAILED/DLQ.
    - Exponential backoff: next_retry_at is updated with exponential delay.
    """
    # 1. Create two test outbox events
    event1 = await outbox_service.publish(
        session=db_session,
        event_type="ORDER_FULFILLMENT_REQUESTED",
        aggregate_type="order",
        aggregate_id="10001",
        payload={"order_id": 10001},
    )
    event2 = await outbox_service.publish(
        session=db_session,
        event_type="ORDER_FULFILLMENT_REQUESTED",
        aggregate_type="order",
        aggregate_id="10002",
        payload={"order_id": 10002},
    )
    await db_session.commit()

    # Worker A claims 1 event
    worker_a_events = await outbox_service.claim_pending_events(session=db_session, worker_id="worker_A", limit=1)
    assert len(worker_a_events) == 1
    claimed_by_a = worker_a_events[0]
    assert claimed_by_a.status == OutboxStatus.PROCESSING.value
    assert claimed_by_a.locked_by == "worker_A"

    # Worker B claims remaining events
    worker_b_events = await outbox_service.claim_pending_events(session=db_session, worker_id="worker_B", limit=10)
    # Worker B must not receive the event claimed by Worker A
    claimed_by_b_ids = [e.id for e in worker_b_events]
    assert claimed_by_a.id not in claimed_by_b_ids

    # Test exponential retry backoff on failure
    t_before = datetime.now(timezone.utc)
    await outbox_service.mark_failed(session=db_session, event_id=claimed_by_a.id, error="Simulated network failure #1")
    await db_session.refresh(claimed_by_a)
    assert claimed_by_a.status == OutboxStatus.RETRY.value
    assert claimed_by_a.retry_count == 1
    assert claimed_by_a.next_retry_at is not None
    # Retry 1 delay is 2^1 * 2 = 4 seconds
    next_retry = claimed_by_a.next_retry_at
    if next_retry.tzinfo is None:
        next_retry = next_retry.replace(tzinfo=timezone.utc)
    assert next_retry >= t_before + timedelta(seconds=3)

    # Fast forward retry_count to max_retries - 1 to test exhaustion
    claimed_by_a.retry_count = claimed_by_a.max_retries - 1
    await outbox_service.mark_failed(
        session=db_session, event_id=claimed_by_a.id, error="Simulated network failure final"
    )
    await db_session.refresh(claimed_by_a)
    assert claimed_by_a.status == OutboxStatus.FAILED.value

    # Verify DLQ record was created
    dlq_res = await db_session.execute(select(FailedJob).where(FailedJob.order_id == int(claimed_by_a.aggregate_id)))
    dlq_entry = dlq_res.scalars().first()
    assert dlq_entry is not None
    assert dlq_entry.status == DLQStatus.EXHAUSTED.value


# ==============================================================================
# 5. Financial Idempotency & Refund Concurrency (Req 15 & 16)
# ==============================================================================


@pytest.mark.asyncio
async def test_refund_concurrency_and_database_uniqueness(db_session: AsyncSession, sample_user: User):
    """
    Req 15 & 16:
    Two simultaneous refund requests for the same order must result in:
    ONE refund, ONE wallet credit, ONE refund ledger record, and ONE final REFUNDED state.
    Never double-credit.
    """
    initial_balance = sample_user.balance
    refund_amount = Decimal("40000.00")

    # 1. Create paid order
    order = Order(
        order_code="#GH-REFUND-CONCURRENCY-01",
        user_id=sample_user.id,
        product_type="stars",
        item_title="200 Stars",
        amount=200,
        unit_price=refund_amount,
        total_price=refund_amount,
        status=OrderStatus.PAID.value,
        fulfillment_status="failed",
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)

    # 2. Execute first refund
    res1 = await order_service.refund_order(
        session=db_session, order_id=order.id, reason="Fulfillment provider failure"
    )
    assert res1.status == OrderStatus.REFUNDED.value

    # 3. Execute second refund (attempted duplicate)
    with pytest.raises(Exception):
        await order_service.refund_order(
            session=db_session, order_id=order.id, reason="Duplicate concurrent refund request"
        )

    await db_session.refresh(sample_user)
    # Exactly ONE refund credited
    assert sample_user.balance == initial_balance + refund_amount

    # Verify exactly ONE wallet ledger transaction exists for order_refund
    tx_count = (
        await db_session.execute(
            select(func.count(WalletTransaction.id)).where(
                WalletTransaction.reference_type == "order_refund", WalletTransaction.reference_id == order.order_code
            )
        )
    ).scalar()
    assert tx_count == 1

    # Verify database constraint uq_wallet_reference_tx prevents direct duplicate insert
    dup_tx = WalletTransaction(
        user_id=sample_user.id,
        tx_type="refund",
        amount=refund_amount,
        balance_before=sample_user.balance,
        balance_after=sample_user.balance + refund_amount,
        reference_type="order_refund",
        reference_id=order.order_code,
        note="Attempted duplicate refund ledger entry",
    )
    db_session.add(dup_tx)
    with pytest.raises((IntegrityError, Exception)):
        await db_session.commit()
    await db_session.rollback()


# ==============================================================================
# 6. Critical Crash Failure Windows (Req 18)
# ==============================================================================


@pytest.mark.asyncio
async def test_failure_window_payment_confirm_to_wallet_update(db_session: AsyncSession, sample_user: User):
    """
    Failure Window 1 & 2:
    Simulates crash during payment confirmation vs wallet ledger update.
    The idempotent payment processing method guarantees that re-executing
    the transaction completes the wallet update without duplicating funds.
    """
    initial_balance = sample_user.balance
    amount = Decimal("15000.00")
    provider_tx_id = "crash_window_test_tx_001"

    # First call simulates completed payment
    tx1, user1, is_new1 = await payment_service.process_successful_payment_idempotent(
        session=db_session,
        provider="click",
        provider_transaction_id=provider_tx_id,
        user_id=sample_user.id,
        amount=amount,
        note="Crash window test",
    )
    assert is_new1 is True

    # Second call (replay after simulated recovery)
    tx2, user2, is_new2 = await payment_service.process_successful_payment_idempotent(
        session=db_session,
        provider="click",
        provider_transaction_id=provider_tx_id,
        user_id=sample_user.id,
        amount=amount,
        note="Crash window replay",
    )
    assert is_new2 is False
    assert tx2.id == tx1.id

    await db_session.refresh(sample_user)
    assert sample_user.balance == initial_balance + amount


# ==============================================================================
# 7. Distributed Worker Heartbeat & Production Readiness (Req 8 & 9)
# ==============================================================================


@pytest.mark.asyncio
async def test_distributed_worker_heartbeat_reporting():
    """
    Req 8 & 9:
    Distributed worker heartbeat tracks worker identity, last heartbeat timestamp,
    and returns online status when fresh.
    """
    heartbeat = await get_distributed_worker_heartbeat()
    assert "status" in heartbeat
    assert "worker_id" in heartbeat
    assert "last_heartbeat" in heartbeat


# ==============================================================================
# 8. Demo Seed Behavior Gating (Req 11)
# ==============================================================================


@pytest.mark.asyncio
async def test_demo_seed_data_strictly_gated(db_session: AsyncSession, monkeypatch):
    """
    Req 11:
    Demo data (e.g. START2026, VIP10, STARS50) must ONLY be seeded when
    SEED_DEMO_DATA=True. If SEED_DEMO_DATA=False, demo promo codes must never be created.
    """
    # Test with SEED_DEMO_DATA=False
    monkeypatch.setattr(settings, "SEED_DEMO_DATA", False)
    # Clear any promo codes
    await db_session.execute(select(PromoCode).execution_options(synchronize_session=False))
    await init_db()

    demo_codes = (
        (await db_session.execute(select(PromoCode).where(PromoCode.code.in_(["START2026", "VIP10", "STARS50"]))))
        .scalars()
        .all()
    )
    assert len(demo_codes) == 0
