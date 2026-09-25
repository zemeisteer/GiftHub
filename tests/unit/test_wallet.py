from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InsufficientBalanceError
from app.models.user import User
from app.services.wallet.service import wallet_service


@pytest.mark.asyncio
async def test_credit_balance(db_session: AsyncSession, sample_user: User):
    initial_balance = sample_user.balance
    credit_amount = Decimal("50000.50")

    user, tx = await wallet_service.credit_balance(
        session=db_session,
        user_id=sample_user.id,
        amount=credit_amount,
        tx_type="deposit",
        reference_type="click",
        reference_id="click_tx_123",
    )

    await db_session.refresh(sample_user)
    assert sample_user.balance == initial_balance + credit_amount
    assert tx.balance_before == initial_balance
    assert tx.balance_after == initial_balance + credit_amount
    assert tx.tx_type == "deposit"
    assert tx.amount == credit_amount


@pytest.mark.asyncio
async def test_debit_balance_success(db_session: AsyncSession, sample_user: User):
    initial_balance = sample_user.balance  # 150,000
    debit_amount = Decimal("70000.00")

    user, tx = await wallet_service.debit_balance(
        session=db_session,
        user_id=sample_user.id,
        amount=debit_amount,
        tx_type="purchase",
        reference_type="order",
        reference_id="order_999",
    )

    await db_session.refresh(sample_user)
    assert sample_user.balance == initial_balance - debit_amount
    assert tx.balance_before == initial_balance
    assert tx.balance_after == initial_balance - debit_amount
    assert tx.tx_type == "purchase"


@pytest.mark.asyncio
async def test_debit_balance_insufficient_funds(db_session: AsyncSession, sample_user: User):
    initial_balance = sample_user.balance  # 150,000
    excessive_amount = Decimal("200000.00")

    with pytest.raises(InsufficientBalanceError):
        await wallet_service.debit_balance(
            session=db_session,
            user_id=sample_user.id,
            amount=excessive_amount,
            tx_type="purchase",
            reference_type="order",
            reference_id="order_1000",
        )

    await db_session.refresh(sample_user)
    assert sample_user.balance == initial_balance


@pytest.mark.asyncio
async def test_admin_adjustment(db_session: AsyncSession, sample_user: User, sample_admin: User):
    initial_balance = sample_user.balance
    adjustment_amount = Decimal("-25000.00")

    user, tx = await wallet_service.adjust_balance_admin(
        session=db_session,
        admin_id=sample_admin.id,
        user_id=sample_user.id,
        amount=adjustment_amount,
        reason="Manual correction for overcharge",
    )

    await db_session.refresh(sample_user)
    assert sample_user.balance == initial_balance + adjustment_amount
    assert tx.tx_type == "admin_adjustment"
    assert "Manual correction" in tx.note
