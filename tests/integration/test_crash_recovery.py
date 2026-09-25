import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dlq import DLQStatus, FailedJob
from app.models.order import Order, OrderStatus
from app.models.outbox import OutboxEvent, OutboxStatus
from app.models.payment import PaymentTransaction
from app.models.user import User
from app.models.wallet import WalletTransaction
from app.services.dlq.service import dlq_service
from app.services.orders.service import order_service
from app.services.outbox.service import outbox_service
from app.services.payments.service import payment_service
from app.services.providers.circuit_breaker import CircuitBreaker, CircuitState
from app.services.wallet.service import wallet_service
from app.services.worker import process_outbox_events_cycle


@pytest.mark.asyncio
async def test_crash_after_payment_commit_outbox_recovery(db_session: AsyncSession, monkeypatch):
    """
    Crash Scenario 1:
    Server crashes immediately after payment commit before in-memory queue receives the job.
    Transactional Outbox guarantees that the event is picked up and fulfilled on worker restart.
    """
    from app.services.fragment import fragment_client
    async def mock_success(*args, **kwargs):
        return {"success": True, "tx_hash": "mock_tx_hash_12345", "fulfilled": True}

    monkeypatch.setattr(fragment_client, "fulfill_order", mock_success)

    # 1. Create user and order
    user = User(id=9901, first_name="OutboxUser", balance=Decimal("100000.00"))
    db_session.add(user)
    await db_session.flush()

    order = Order(
        order_code="#GH-OUTBOX-01",
        user_id=user.id,
        product_type="stars",
        item_title="50 Stars",
        amount=50,
        unit_price=Decimal("11000.00"),
        total_price=Decimal("11000.00"),
        status=OrderStatus.CREATED.value,
        fulfillment_status="pending"
    )
    db_session.add(order)
    await db_session.commit()

    # 2. Simulate payment processing which atomically emits an OutboxEvent
    res = await payment_service.process_successful_payment_idempotent(
        session=db_session,
        provider="click",
        provider_transaction_id="click_outbox_test_101",
        amount=Decimal("11000.00"),
        user_id=user.id,
        order_id=order.id
    )
    assert res.is_new is True

    # Check that order is PAID and OutboxEvent was created with PENDING status
    await db_session.refresh(order)
    assert order.status == OrderStatus.PAID.value

    outbox_stmt = select(OutboxEvent).where(
        OutboxEvent.aggregate_id == str(order.id),
        OutboxEvent.event_type == "ORDER_FULFILLMENT_REQUESTED"
    )
    outbox_res = await db_session.execute(outbox_stmt)
    event = outbox_res.scalars().first()
    assert event is not None
    assert event.status == OutboxStatus.PENDING.value

    # 3. Simulate process crash: in-memory queue is lost!
    # Worker restarts and executes process_outbox_events_cycle
    # (Mock fulfillment client automatically fulfills test orders)
    await process_outbox_events_cycle(session=db_session)

    # Verify event is now PROCESSED
    await db_session.refresh(event)
    assert event.status == OutboxStatus.PROCESSED.value


@pytest.mark.asyncio
async def test_fulfillment_retries_exhausted_routes_to_dlq(db_session: AsyncSession, monkeypatch):
    """
    Crash Scenario 2:
    External fulfillment provider repeatedly fails. After 3 retries, the job is
    automatically routed to the Dead Letter Queue (DLQ) for manual admin recovery.
    """
    user = User(id=9902, first_name="DLQUser", balance=Decimal("100000.00"))
    db_session.add(user)
    await db_session.flush()

    order = Order(
        order_code="#GH-DLQ-02",
        user_id=user.id,
        product_type="stars",
        item_title="100 Stars",
        amount=100,
        unit_price=Decimal("21500.00"),
        total_price=Decimal("21500.00"),
        status=OrderStatus.PAID.value,
        fulfillment_status="pending",
        fulfillment_attempts=2 # Already failed twice
    )
    db_session.add(order)
    await db_session.commit()

    # Mock fragment client to fail
    from app.services.fragment import fragment_client
    async def mock_fail(*args, **kwargs):
        return {"success": False, "error": "Fragment network timeout 504 Gateway Error"}

    monkeypatch.setattr(fragment_client, "fulfill_order", mock_fail)

    from app.services.fulfillment.service import fulfillment_service
    res = await fulfillment_service.fulfill_order_automated(session=db_session, order_id=order.id)
    assert res["success"] is False

    await db_session.refresh(order)
    assert order.status == OrderStatus.FAILED.value
    assert order.fulfillment_status == "manual_review"

    # Verify job is preserved in DLQ
    dlq_stmt = select(FailedJob).where(FailedJob.order_id == order.id)
    dlq_res = await db_session.execute(dlq_stmt)
    dlq_job = dlq_res.scalars().first()
    assert dlq_job is not None
    assert dlq_job.status == DLQStatus.EXHAUSTED.value
    assert "Fragment network timeout" in dlq_job.error_message


@pytest.mark.asyncio
async def test_circuit_breaker_trips_on_provider_failures(db_session: AsyncSession):
    """
    Crash Scenario 5:
    Circuit breaker trips to OPEN after threshold failures and rejects requests without latency.
    """
    cb = CircuitBreaker()
    cb.FAILURE_THRESHOLD = 3

    assert cb.can_execute("click") is True

    # Record 2 failures
    cb.record_failure("click", "Connection reset")
    cb.record_failure("click", "HTTP 502 Bad Gateway")
    assert cb.can_execute("click") is True

    # 3rd failure trips the breaker
    cb.record_failure("click", "Timeout")
    assert cb.can_execute("click") is False
    assert cb._get_or_init_state("click")["state"] == CircuitState.OPEN.value

    # Reset on success
    cb.record_success("click")
    assert cb.can_execute("click") is True
    assert cb._get_or_init_state("click")["state"] == CircuitState.CLOSED.value


@pytest.mark.asyncio
async def test_checkout_idempotency_prevents_duplicate_purchases(db_session: AsyncSession):
    """
    Crash Scenario 6:
    Repeated button clicks or network retries with identical Idempotency-Key
    return the exact same order without double charges.
    """
    user = User(id=9903, first_name="IdempUser", balance=Decimal("50000.00"))
    db_session.add(user)
    await db_session.commit()

    idemp_key = "idemp_checkout_uuid_999"

    # First checkout call
    order1, _, _ = await order_service.create_order(
        session=db_session,
        user_id=user.id,
        product_type="stars",
        item_title="50 Stars",
        amount=50,
        payment_method="balance",
        idempotency_key=idemp_key
    )

    await db_session.refresh(user)
    initial_balance = user.balance

    # Second checkout call with SAME idempotency key
    order2, _, _ = await order_service.create_order(
        session=db_session,
        user_id=user.id,
        product_type="stars",
        item_title="50 Stars",
        amount=50,
        payment_method="balance",
        idempotency_key=idemp_key
    )

    # Must return the identical order
    assert order1.id == order2.id
    assert order1.order_code == order2.order_code

    # Balance must NOT be deducted twice
    await db_session.refresh(user)
    assert user.balance == initial_balance


@pytest.mark.asyncio
async def test_database_financial_constraints(db_session: AsyncSession):
    """
    Crash Scenario 7:
    Database check constraints prevent invalid financial invariants (e.g. negative balance).
    """
    # 1. Attempt to insert user with negative balance
    bad_user = User(id=9904, first_name="BadUser", balance=Decimal("-500.00"))
    db_session.add(bad_user)
    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()

    # 2. Attempt to insert wallet transaction with zero amount (forbidden by chk_wallet_amount_non_zero)
    good_user_id = 9905
    good_user = User(id=good_user_id, first_name="GoodUser", balance=Decimal("100.00"))
    db_session.add(good_user)
    await db_session.commit()

    bad_tx = WalletTransaction(
        user_id=good_user_id,
        tx_type="deposit",
        amount=Decimal("0.00"), # Zero amount forbidden by check constraint
        balance_before=Decimal("100.00"),
        balance_after=Decimal("100.00")
    )
    db_session.add(bad_tx)
    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()

    # 3. Attempt to insert wallet transaction with negative balance_after
    bad_balance_tx = WalletTransaction(
        user_id=good_user_id,
        tx_type="purchase",
        amount=Decimal("-200.00"),
        balance_before=Decimal("100.00"),
        balance_after=Decimal("-100.00") # Negative balance forbidden
    )
    db_session.add(bad_balance_tx)
    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()
