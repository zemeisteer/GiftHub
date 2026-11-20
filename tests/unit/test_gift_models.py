from decimal import Decimal

import pytest

from app.models.gift import GiftSyncState, TelegramGift
from app.models.order import Order

pytestmark = pytest.mark.asyncio


async def test_gift_defaults(db_session):
    db_session.add(TelegramGift(id="g1", star_count=15))
    await db_session.commit()
    gift = await db_session.get(TelegramGift, "g1")
    assert gift.enabled is True
    assert gift.available is True
    assert gift.is_premium is False
    assert gift.is_limited is False
    assert gift.emoji == "🎁"


async def test_order_stores_52_bit_recipient_id(db_session, sample_user):
    rid = 4_503_599_627_370_495
    order = Order(
        order_code="GH-T1",
        user_id=sample_user.id,
        product_type="gift",
        item_title="Gift",
        unit_price=Decimal("1000.00"),
        total_price=Decimal("1000.00"),
        recipient_user_id=rid,
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    assert order.recipient_user_id == rid


async def test_sync_state_single_row(db_session):
    db_session.add(GiftSyncState(id=1))
    await db_session.commit()
    state = await db_session.get(GiftSyncState, 1)
    assert state is not None
    assert state.bot_star_balance is None
