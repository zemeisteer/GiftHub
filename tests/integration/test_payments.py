from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import OrderStatus
from app.models.payment import PaymentTransaction
from app.models.referral import ReferralReward
from app.models.user import User
from app.services.orders.service import orderService
from app.services.payments.service import payment_service


@pytest.mark.asyncio
async def test_duplicate_webhook_idempotency(db_session: AsyncSession, sample_user: User):
    """
    CRITICAL TEST:
    Send the same successful payment webhook 5 times.
    Expected:
    - User balance credited exactly ONCE
    - PaymentTransaction recorded exactly ONCE
    - Order transitioned to PAID exactly ONCE
    - Referral bonus awarded exactly ONCE
    """
    # 1. Create referrer and set up referral relationship
    referrer = User(
        id=88888888,
        username="topreferrer",
        first_name="Top",
        last_name="Referrer",
        balance=Decimal("0.00"),
        role="user"
    )
    db_session.add(referrer)
    await db_session.flush()

    sample_user.referrer_id = referrer.telegram_id
    initial_user_balance = sample_user.balance
    initial_referrer_balance = referrer.balance

    # 2. Create an order awaiting payment
    order = await orderService.create_order_authoritative(
        session=db_session,
        user_id=sample_user.telegram_id,
        product="stars",
        quantity=50,
        recipient="self",
        recipient_id=str(sample_user.telegram_id),
        payment_method="click"
    )
    await orderService.transition_order_state(db_session, order.id, OrderStatus.AWAITING_PAYMENT)
    order_amount = order.total_price

    provider = "click"
    provider_tx_id = "click_tx_unique_99999"

    # 3. Simulate calling payment confirmation 5 times with identical parameters
    results = []
    for i in range(5):
        ptx = await payment_service.process_successful_payment_idempotent(
            session=db_session,
            provider=provider,
            provider_transaction_id=provider_tx_id,
            amount=order_amount,
            currency="UZS",
            telegram_id=sample_user.telegram_id,
            order_id=order.id
        )
        results.append(ptx)

    # 4. Verify all 5 calls returned the same payment transaction
    assert all(r.provider_transaction_id == provider_tx_id for r in results)

    # 5. Check PaymentTransaction count in DB
    ptx_query = await db_session.execute(
        select(PaymentTransaction).where(
            PaymentTransaction.provider == provider,
            PaymentTransaction.provider_transaction_id == provider_tx_id
        )
    )
    ptx_records = ptx_query.scalars().all()
    assert len(ptx_records) == 1

    # 6. Check Order status
    await db_session.refresh(order)
    assert order.status == OrderStatus.PAID.value

    # 7. Check ReferralReward records
    ref_query = await db_session.execute(
        select(ReferralReward).where(ReferralReward.order_id == order.id)
    )
    ref_records = ref_query.scalars().all()
    assert len(ref_records) == 1

    # 8. Check Referrer balance credited exactly once
    await db_session.refresh(referrer)
    assert referrer.balance > initial_referrer_balance
    from decimal import ROUND_HALF_UP
    expected_bonus = (order_amount * Decimal("0.05")).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    assert referrer.balance == initial_referrer_balance + expected_bonus


@pytest.mark.asyncio
async def test_wallet_topup_webhook_idempotency(db_session: AsyncSession, sample_user: User):
    """
    Test direct wallet balance topup via webhook executed multiple times.
    """
    initial_balance = sample_user.balance
    topup_amount = Decimal("25000.00")
    provider = "payme"
    provider_tx_id = "payme_receipt_77777"

    for _ in range(3):
        await payment_service.process_successful_payment_idempotent(
            session=db_session,
            provider=provider,
            provider_transaction_id=provider_tx_id,
            amount=topup_amount,
            currency="UZS",
            telegram_id=sample_user.telegram_id,
            order_id=None
        )

    await db_session.refresh(sample_user)
    # Balance must only have increased once
    assert sample_user.balance == initial_balance + topup_amount
