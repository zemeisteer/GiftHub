
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidOrderStateError
from app.models.order import OrderStatus
from app.models.user import User
from app.services.orders.service import orderService


@pytest.mark.asyncio
async def test_valid_refund_flow(db_session: AsyncSession, sample_user: User, sample_admin: User):
    initial_balance = sample_user.balance

    # 1. Create order with wallet payment (instantly marked PAID)
    order = await orderService.create_order_authoritative(
        session=db_session,
        user_id=sample_user.id,
        product="stars",
        quantity=100,
        recipient="self",
        recipient_id=str(sample_user.id),
        payment_method="wallet"
    )
    order_price = order.total_price

    # 2. Process refund
    refunded_order = await orderService.refund_order(
        session=db_session,
        order_id=order.id,
        admin_telegram_id=sample_admin.id,
        reason="Customer requested cancellation before delivery"
    )

    # 3. Assertions
    assert refunded_order.status == OrderStatus.REFUNDED.value
    assert refunded_order.refunded_at is not None

    await db_session.refresh(sample_user)
    # Balance should be restored to initial
    assert sample_user.balance == initial_balance


@pytest.mark.asyncio
async def test_duplicate_refund_prevented(db_session: AsyncSession, sample_user: User, sample_admin: User):
    order = await orderService.create_order_authoritative(
        session=db_session,
        user_id=sample_user.id,
        product="stars",
        quantity=50,
        recipient="self",
        recipient_id=str(sample_user.id),
        payment_method="wallet"
    )

    # First refund succeeds
    await orderService.refund_order(
        session=db_session,
        order_id=order.id,
        admin_telegram_id=sample_admin.id,
        reason="First refund"
    )

    await db_session.refresh(sample_user)
    balance_after_first_refund = sample_user.balance

    # Second refund attempt must fail with InvalidOrderStateError
    with pytest.raises(InvalidOrderStateError):
        await orderService.refund_order(
            session=db_session,
            order_id=order.id,
            admin_telegram_id=sample_admin.id,
            reason="Second refund attempt"
        )

    await db_session.refresh(sample_user)
    # Balance must not have changed again
    assert sample_user.balance == balance_after_first_refund


@pytest.mark.asyncio
async def test_refund_unpaid_order_fails(db_session: AsyncSession, sample_user: User, sample_admin: User):
    order = await orderService.create_order_authoritative(
        session=db_session,
        user_id=sample_user.id,
        product="stars",
        quantity=50,
        recipient="self",
        recipient_id=str(sample_user.id),
        payment_method="click"
    )
    # Order is in CREATED state (unpaid)
    assert order.status == OrderStatus.CREATED.value

    with pytest.raises(InvalidOrderStateError):
        await orderService.refund_order(
            session=db_session,
            order_id=order.id,
            admin_telegram_id=sample_admin.id,
            reason="Trying to refund unpaid order"
        )
