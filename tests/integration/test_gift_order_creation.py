from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.exceptions import GiftHubException
from app.models.gift import GiftSyncState, TelegramGift
from app.models.order import Order, OrderStatus
from app.models.user import User
from app.services.gift_recipients import resolve_gift_recipient
from app.services.orders.service import OrderService

BUYER_ID = 12345678  # sample_user (username "testbuyer")


async def _setup(db_session, balance=1000, gifts=None):
    db_session.add_all(gifts if gifts is not None else [TelegramGift(id="g15", star_count=15)])
    db_session.add(GiftSyncState(id=1, bot_star_balance=balance))
    await db_session.commit()


async def _order(db_session, recipient=None, gift_id="g15"):
    return await OrderService.create_order(
        db_session,
        user_id=BUYER_ID,
        product_type="gift",
        item_title=gift_id,
        recipient_username=recipient,
    )


async def _order_count(db_session):
    return (await db_session.execute(select(func.count()).select_from(Order))).scalar_one()


async def _balance(db_session, user):
    await db_session.refresh(user)
    return user.balance


async def test_self_gift_uses_buyer_id_even_if_client_sends_other_id_string_for_self(db_session, sample_user):
    assert await resolve_gift_recipient(db_session, BUYER_ID, None) == BUYER_ID
    assert await resolve_gift_recipient(db_session, BUYER_ID, "") == BUYER_ID
    assert await resolve_gift_recipient(db_session, BUYER_ID, "@TestBuyer") == BUYER_ID
    assert await resolve_gift_recipient(db_session, BUYER_ID, "testbuyer") == BUYER_ID


async def test_numeric_id_is_accepted(db_session, sample_user):
    assert await resolve_gift_recipient(db_session, BUYER_ID, "987654321") == 987654321


async def test_52_bit_id_not_truncated(db_session, sample_user):
    big = 4_503_599_627_370_495
    await _setup(db_session)
    order, _, _ = await _order(db_session, recipient=str(big))
    await db_session.refresh(order)
    assert order.recipient_user_id == big


async def test_username_resolves_via_users_table_case_insensitive(db_session, sample_user):
    db_session.add(User(id=555000111, username="FriendUser", first_name="F", balance=Decimal("0")))
    await db_session.commit()
    assert await resolve_gift_recipient(db_session, BUYER_ID, "@frienduser") == 555000111
    assert await resolve_gift_recipient(db_session, BUYER_ID, "FRIENDUSER") == 555000111


async def test_unknown_username_rejected_before_charge(db_session, sample_user):
    await _setup(db_session)
    before = await _balance(db_session, sample_user)
    with pytest.raises(GiftHubException, match="Bu odam botdan foydalanmagan"):
        await _order(db_session, recipient="@nobody_here")
    assert await _balance(db_session, sample_user) == before
    assert await _order_count(db_session) == 0


@pytest.mark.parametrize("bad", ["@a", "12", "12345678901234567", "bad name", "@@abcde", "9abcde", "a-bcde"])
async def test_malformed_recipient_rejected(db_session, sample_user, bad):
    with pytest.raises(GiftHubException):
        await resolve_gift_recipient(db_session, BUYER_ID, bad)


async def test_unorderable_gift_rejected_before_charge(db_session, sample_user):
    await _setup(db_session, gifts=[TelegramGift(id="off", star_count=15, enabled=False)])
    before = await _balance(db_session, sample_user)
    with pytest.raises(GiftHubException):
        await _order(db_session, gift_id="off")
    assert await _balance(db_session, sample_user) == before
    assert await _order_count(db_session) == 0


async def test_insufficient_bot_stars_rejected_before_charge(db_session, sample_user):
    await _setup(db_session, balance=10)
    before = await _balance(db_session, sample_user)
    with pytest.raises(GiftHubException, match="hozir yuborib bo'lmaydi"):
        await _order(db_session)
    assert await _balance(db_session, sample_user) == before
    assert await _order_count(db_session) == 0


async def test_unknown_balance_allows_order(db_session, sample_user):
    await _setup(db_session, balance=None)
    order, _, _ = await _order(db_session)
    assert order.id is not None


async def test_reservation_blocks_oversubscription(db_session, sample_user):
    await _setup(db_session, balance=15)
    await _order(db_session)  # reserves 15
    with pytest.raises(GiftHubException, match="hozir yuborib bo'lmaydi"):
        await _order(db_session)
    assert await _order_count(db_session) == 1


async def test_successful_gift_order_stores_price_and_recipient_user_id(db_session, sample_user):
    await _setup(db_session)
    before = await _balance(db_session, sample_user)
    order, _, _ = await _order(db_session)
    await db_session.refresh(order)
    assert order.recipient_user_id == BUYER_ID
    assert order.total_price > Decimal(0)
    assert order.status == OrderStatus.PAID
    assert await _balance(db_session, sample_user) == before - order.total_price


@pytest.mark.parametrize("bad", ["00000", "0000000", "4503599627370496", "9999999999999999"])
async def test_out_of_range_numeric_id_rejected(db_session, sample_user, bad):
    with pytest.raises(GiftHubException, match="noto'g'ri"):
        await resolve_gift_recipient(db_session, BUYER_ID, bad)


async def test_price_lock_for_cheap_gift_cannot_lower_price_of_pricier_gift(db_session, sample_user):
    from app.services.pricing.service import PricingService

    await _setup(
        db_session,
        gifts=[TelegramGift(id="cheap", star_count=15), TelegramGift(id="pricey", star_count=100)],
    )
    lock = await PricingService.create_price_lock(db_session, "gift", 1, user_id=BUYER_ID, item_title="cheap")
    fresh = await PricingService.get_authoritative_price(db_session, "gift", 1, item_title="pricey")
    assert fresh["total_price_decimal"] > lock.total_price

    order, _, _ = await OrderService.create_order(
        db_session,
        user_id=BUYER_ID,
        product_type="gift",
        item_title="pricey",
        price_lock_id=lock.id,
    )
    assert order.total_price == fresh["total_price_decimal"]
    assert order.price_lock_id is None


async def test_gift_order_with_bogus_price_lock_succeeds_at_fresh_price(db_session, sample_user):
    from app.services.pricing.service import PricingService

    await _setup(db_session)
    fresh = await PricingService.get_authoritative_price(db_session, "gift", 1, item_title="g15")
    order, _, _ = await OrderService.create_order(
        db_session,
        user_id=BUYER_ID,
        product_type="gift",
        item_title="g15",
        price_lock_id="pl_doesnotexist",
    )
    assert order.total_price == fresh["total_price_decimal"]
