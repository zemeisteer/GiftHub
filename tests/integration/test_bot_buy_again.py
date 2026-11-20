"""Bot "buy again" charges the buyer exactly once (order_service.create_order already debits the wallet)."""

import types
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.handlers.users import orders as orders_handler
from app.models.order import Order, OrderStatus
from app.models.outbox import OutboxEvent
from app.models.wallet import WalletTransaction
from app.services.fulfillment.service import fulfillment_service
from app.services.pricing.service import pricing_service

BUYER_ID = 12345678  # sample_user


@pytest.fixture
def factory(db_session, monkeypatch):
    f = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(orders_handler, "AsyncSessionLocal", f)
    return f


@pytest.fixture
def fulfill_spy(monkeypatch):
    spy = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(fulfillment_service, "fulfill_order_automated", spy)
    return spy


def _callback(data):
    return types.SimpleNamespace(
        data=data,
        from_user=types.SimpleNamespace(id=BUYER_ID, username="testbuyer"),
        message=types.SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
        bot=object(),
    )


async def _old_stars_order(db_session):
    order = Order(
        order_code="#GH-OLD-1",
        user_id=BUYER_ID,
        product_type="stars",
        item_title="50 Telegram Stars",
        amount=50,
        unit_price=Decimal("200.00"),
        total_price=Decimal("10000.00"),
        status=OrderStatus.COMPLETED.value,
        fulfillment_status="fulfilled",
        recipient_username="testbuyer",
    )
    db_session.add(order)
    await db_session.commit()
    return order


async def test_buy_again_debits_wallet_once(db_session, sample_user, factory, fulfill_spy):
    await _old_stars_order(db_session)
    price = Decimal(
        str(
            (await pricing_service.get_authoritative_price(db_session, product_type="stars", amount=50))[
                "total_price_decimal"
            ]
        )
    )
    before = sample_user.balance

    await orders_handler.cb_order_confirm_buy_again(_callback("order:confirm_buyagain:#GH-OLD-1"))

    await db_session.refresh(sample_user)
    assert before - sample_user.balance == price  # not 2 x price
    new_order = (await db_session.execute(select(Order).where(Order.order_code != "#GH-OLD-1"))).scalars().one()
    assert new_order.status == OrderStatus.PAID.value
    debits = (
        await db_session.execute(
            select(func.count()).select_from(WalletTransaction).where(WalletTransaction.user_id == BUYER_ID)
        )
    ).scalar_one()
    assert debits == 1
    assert len((await db_session.execute(select(OutboxEvent))).scalars().all()) == 1
    fulfill_spy.assert_awaited_once()
    assert fulfill_spy.await_args.kwargs.get("bot") is not None


async def test_buy_again_insufficient_balance_creates_nothing(db_session, sample_user, factory, fulfill_spy):
    await _old_stars_order(db_session)
    sample_user.balance = Decimal("1.00")
    await db_session.commit()
    cb = _callback("order:confirm_buyagain:#GH-OLD-1")

    await orders_handler.cb_order_confirm_buy_again(cb)

    await db_session.refresh(sample_user)
    assert sample_user.balance == Decimal("1.00")
    assert (await db_session.execute(select(func.count()).select_from(Order))).scalar_one() == 1
    assert "yetarli mablag'" in cb.message.answer.await_args.args[0]
    fulfill_spy.assert_not_awaited()


async def test_buy_again_create_order_error_is_shown_not_raised(
    db_session, sample_user, factory, fulfill_spy, monkeypatch
):
    from app.core.exceptions import GiftHubException
    from app.services.orders.service import order_service

    await _old_stars_order(db_session)
    monkeypatch.setattr(order_service, "create_order", AsyncMock(side_effect=GiftHubException("Xaridlar to'xtatilgan")))
    cb = _callback("order:confirm_buyagain:#GH-OLD-1")
    before = sample_user.balance

    await orders_handler.cb_order_confirm_buy_again(cb)

    assert cb.answer.await_args.kwargs.get("show_alert") is True
    assert "to'xtatilgan" in cb.answer.await_args.args[0]
    await db_session.refresh(sample_user)
    assert sample_user.balance == before
    fulfill_spy.assert_not_awaited()
