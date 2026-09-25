from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidOrderStateError
from app.models.order import OrderStatus
from app.models.user import User
from app.services.orders.service import orderService


@pytest.mark.asyncio
async def test_order_creation_authoritative_price(db_session: AsyncSession, sample_user: User):
    order = await orderService.create_order_authoritative(
        session=db_session,
        user_id=sample_user.telegram_id,
        product="stars",
        quantity=50,
        recipient="self",
        recipient_id=str(sample_user.telegram_id),
        payment_method="click",
    )
    assert order.id is not None
    assert order.status == OrderStatus.CREATED.value
    assert order.total_price > Decimal(0)
    assert order.created_at is not None


@pytest.mark.asyncio
async def test_order_state_transitions_lifecycle(db_session: AsyncSession, sample_user: User):
    order = await orderService.create_order_authoritative(
        session=db_session,
        user_id=sample_user.telegram_id,
        product="stars",
        quantity=100,
        recipient="self",
        recipient_id=str(sample_user.telegram_id),
        payment_method="click",
    )

    # CREATED -> AWAITING_PAYMENT
    await orderService.transition_order_state(db_session, order.id, OrderStatus.AWAITING_PAYMENT)
    await db_session.refresh(order)
    assert order.status == OrderStatus.AWAITING_PAYMENT.value

    # AWAITING_PAYMENT -> PAID
    await orderService.transition_order_state(db_session, order.id, OrderStatus.PAID)
    await db_session.refresh(order)
    assert order.status == OrderStatus.PAID.value
    assert order.paid_at is not None

    # PAID -> PROCESSING
    await orderService.transition_order_state(db_session, order.id, OrderStatus.PROCESSING)
    await db_session.refresh(order)
    assert order.status == OrderStatus.PROCESSING.value
    assert order.processing_at is not None

    # PROCESSING -> COMPLETED
    await orderService.transition_order_state(db_session, order.id, OrderStatus.COMPLETED)
    await db_session.refresh(order)
    assert order.status == OrderStatus.COMPLETED.value
    assert order.completed_at is not None


@pytest.mark.asyncio
async def test_order_invalid_state_transition_fails(db_session: AsyncSession, sample_user: User):
    order = await orderService.create_order_authoritative(
        session=db_session,
        user_id=sample_user.telegram_id,
        product="stars",
        quantity=50,
        recipient="self",
        recipient_id=str(sample_user.telegram_id),
        payment_method="wallet",
    )
    # Move to COMPLETED: PAID -> COMPLETED
    await orderService.transition_order_state(db_session, order.id, OrderStatus.COMPLETED)

    # Illegal transition: COMPLETED -> PROCESSING
    with pytest.raises(InvalidOrderStateError):
        await orderService.transition_order_state(db_session, order.id, OrderStatus.PROCESSING)
