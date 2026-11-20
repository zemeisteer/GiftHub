from decimal import Decimal

import pytest

from app.core.exceptions import GiftHubException
from app.models.gift import GiftSyncState, TelegramGift
from app.models.order import Order
from app.services import gift_catalog
from tests.gift_fakes import FakeGiftBot, make_gift

pytestmark = pytest.mark.asyncio


async def _all(db_session) -> dict[str, TelegramGift]:
    from sqlalchemy import select

    rows = (await db_session.execute(select(TelegramGift))).scalars().all()
    return {g.id: g for g in rows}


async def test_sync_inserts_and_updates(db_session):
    db_session.add(
        TelegramGift(
            id="g1",
            star_count=10,
            enabled=False,
            title="Custom",
            price_override_uzs=Decimal("5000.00"),
            is_limited=True,
            remaining_count=100,
        )
    )
    await db_session.commit()
    bot = FakeGiftBot([make_gift("g1", 25, total_count=500, remaining_count=40), make_gift("g2", 15)])

    result = await gift_catalog.sync(db_session, bot)

    assert result == {"added": 1, "updated": 1, "unavailable": 0}
    gifts = await _all(db_session)
    assert gifts["g1"].star_count == 25
    assert gifts["g1"].remaining_count == 40
    assert gifts["g1"].is_limited is True
    assert gifts["g1"].enabled is False
    assert gifts["g1"].title == "Custom"
    assert gifts["g1"].price_override_uzs == Decimal("5000.00")
    assert gifts["g2"].star_count == 15
    assert gifts["g2"].is_limited is False
    assert gifts["g2"].emoji == "🧸"


async def test_sync_marks_missing_unavailable(db_session):
    db_session.add_all([TelegramGift(id="old", star_count=10), TelegramGift(id="keep", star_count=15)])
    await db_session.commit()

    result = await gift_catalog.sync(db_session, FakeGiftBot([make_gift("keep", 15)]))

    assert result["unavailable"] == 1
    gifts = await _all(db_session)
    assert gifts["old"].available is False
    assert gifts["keep"].available is True


async def test_sync_with_empty_list_keeps_catalog(db_session):
    db_session.add(TelegramGift(id="g1", star_count=10))
    await db_session.commit()

    with pytest.raises(GiftHubException):
        await gift_catalog.sync(db_session, FakeGiftBot([]))

    assert (await _all(db_session))["g1"].available is True
    state = await db_session.get(GiftSyncState, 1)
    assert state.last_sync_error


async def test_sync_error_keeps_catalog(db_session):
    db_session.add(TelegramGift(id="g1", star_count=10))
    await db_session.commit()

    class BrokenBot(FakeGiftBot):
        async def get_available_gifts(self, **kw):
            raise RuntimeError("telegram down")

    with pytest.raises(GiftHubException):
        await gift_catalog.sync(db_session, BrokenBot([make_gift("x")]))

    assert (await _all(db_session))["g1"].available is True
    state = await db_session.get(GiftSyncState, 1)
    assert "telegram down" in state.last_sync_error


async def test_sticker_without_emoji_uses_gift_emoji(db_session):
    await gift_catalog.sync(db_session, FakeGiftBot([make_gift("g1", emoji=None)]))
    assert (await _all(db_session))["g1"].emoji == "🎁"


async def test_sync_stores_balance(db_session):
    await gift_catalog.sync(db_session, FakeGiftBot([make_gift("g1")], balance=777))
    state = await db_session.get(GiftSyncState, 1)
    assert state.bot_star_balance == 777
    assert state.last_sync_at is not None
    assert state.last_sync_error is None


async def test_sync_if_empty(db_session):
    bot = FakeGiftBot([make_gift("g1")])
    assert await gift_catalog.sync_if_empty(db_session, bot) is True
    assert await gift_catalog.sync_if_empty(db_session, bot) is False


async def test_get_orderable_rules(db_session):
    db_session.add_all(
        [
            TelegramGift(id="ok", star_count=15),
            TelegramGift(id="premium", star_count=15, is_premium=True),
            TelegramGift(id="off", star_count=15, enabled=False),
            TelegramGift(id="gone", star_count=15, available=False),
            TelegramGift(id="soldout", star_count=15, is_limited=True, remaining_count=0),
            TelegramGift(id="limited", star_count=15, is_limited=True, remaining_count=3),
        ]
    )
    await db_session.commit()

    assert (await gift_catalog.get_orderable(db_session, "ok")).id == "ok"
    assert (await gift_catalog.get_orderable(db_session, "limited")).id == "limited"
    for bad in ("premium", "off", "gone", "soldout", "missing"):
        with pytest.raises(GiftHubException, match="sotuvda emas"):
            await gift_catalog.get_orderable(db_session, bad)


def _order(code, user_id, gift_id, status, fulfillment, product_type="gift"):
    return Order(
        order_code=code,
        user_id=user_id,
        product_type=product_type,
        item_title=gift_id,
        unit_price=Decimal("1000.00"),
        total_price=Decimal("1000.00"),
        status=status,
        fulfillment_status=fulfillment,
    )


async def test_reserved_stars_counts_unfinished_paid_gift_orders(db_session, sample_user):
    db_session.add_all([TelegramGift(id="g15", star_count=15), TelegramGift(id="g50", star_count=50)])
    uid = sample_user.id
    db_session.add_all(
        [
            _order("R1", uid, "g15", "paid", "pending"),
            _order("R2", uid, "g50", "processing", "processing"),
            _order("R3", uid, "g50", "completed", "fulfilled"),
            _order("R4", uid, "g50", "failed", "failed"),
            _order("R5", uid, "g50", "refunded", "failed"),
            _order("R6", uid, "g50", "awaiting_payment", "pending"),
            _order("R7", uid, "g50", "paid", "pending", product_type="stars"),
        ]
    )
    await db_session.commit()

    assert await gift_catalog.reserved_stars(db_session) == 65


async def test_spendable_none_when_balance_unknown(db_session):
    assert await gift_catalog.spendable_stars(db_session) is None
    db_session.add(GiftSyncState(id=1, bot_star_balance=None))
    await db_session.commit()
    assert await gift_catalog.spendable_stars(db_session) is None


async def test_spendable_subtracts_reserved_and_decrement(db_session, sample_user):
    db_session.add_all([TelegramGift(id="g15", star_count=15), GiftSyncState(id=1, bot_star_balance=100)])
    db_session.add(_order("S1", sample_user.id, "g15", "paid", "pending"))
    await db_session.commit()

    assert await gift_catalog.spendable_stars(db_session) == 85
    await gift_catalog.decrement_cached_balance(db_session, 30)
    assert await gift_catalog.spendable_stars(db_session) == 55
    await gift_catalog.decrement_cached_balance(db_session, 1000)
    state = await db_session.get(GiftSyncState, 1)
    assert state.bot_star_balance == 0


@pytest.mark.skip(reason="Task 3")
async def test_list_public_hides_unorderable_and_has_no_cost(db_session):
    db_session.add_all(
        [
            TelegramGift(id="ok", star_count=15, emoji="🧸"),
            TelegramGift(id="titled", star_count=50, title="Rose", is_limited=True, remaining_count=7),
            TelegramGift(id="premium", star_count=15, is_premium=True),
            TelegramGift(id="off", star_count=15, enabled=False),
            TelegramGift(id="soldout", star_count=15, is_limited=True, remaining_count=0),
        ]
    )
    await db_session.commit()

    items = await gift_catalog.list_public(db_session)

    assert [i["id"] for i in items] == ["ok", "titled"]
    for item in items:
        assert set(item) == {"id", "name", "icon", "price_uzs", "type", "stars", "remaining"}
        assert "cost_uzs" not in item
        assert item["type"] == "gift"
        assert isinstance(item["price_uzs"], float)
    assert items[0]["name"] == "15 ⭐ sovg'a"
    assert items[0]["remaining"] is None
    assert items[1]["name"] == "Rose"
    assert items[1]["remaining"] == 7


@pytest.mark.skip(reason="Task 3")
async def test_list_public_uses_price_override(db_session):
    db_session.add(TelegramGift(id="ov", star_count=15, price_override_uzs=Decimal("12345.00")))
    await db_session.commit()

    items = await gift_catalog.list_public(db_session)

    assert items[0]["price_uzs"] == 12345.0
