import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.methods import SendGift
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.base import utc_now
from app.models.gift import GiftSyncState, TelegramGift
from app.models.notification import InAppNotification
from app.models.order import Order, OrderStatus
from app.models.user import User
from app.services import gift_delivery
from app.services.orders.service import OrderService
from tests.gift_fakes import FakeGiftBot

BUYER_ID = 12345678  # sample_user
RECIPIENT_ID = 987654321
ADMIN_ID = 777000111
METHOD = SendGift(gift_id="g15", user_id=RECIPIENT_ID)


@pytest.fixture(autouse=True)
def _admins(monkeypatch):
    monkeypatch.setattr(settings, "ADMINS", [ADMIN_ID])


@pytest.fixture
def sleeps(monkeypatch):
    calls: list[float] = []

    async def fake_sleep(seconds, *a, **kw):
        calls.append(seconds)

    monkeypatch.setattr(gift_delivery.asyncio, "sleep", fake_sleep)
    return calls


async def _paid_order(db_session, payment_method="balance", star_balance=1000) -> Order:
    db_session.add(TelegramGift(id="g15", star_count=15))
    db_session.add(GiftSyncState(id=1, bot_star_balance=star_balance))
    await db_session.commit()
    order, _, _ = await OrderService.create_order(
        db_session,
        user_id=BUYER_ID,
        product_type="gift",
        item_title="g15",
        recipient_username=str(RECIPIENT_ID),
        payment_method=payment_method,
    )
    return order


async def _reload(db_session, order_id) -> Order:
    return await db_session.get(Order, order_id, populate_existing=True)


async def _wallet(db_session) -> Decimal:
    user = await db_session.get(User, BUYER_ID, populate_existing=True)
    return user.balance


def _to(bot, chat_id):
    return [m["text"] for m in bot.messages if m["chat_id"] == chat_id]


def _bad(msg):
    return TelegramBadRequest(method=METHOD, message=msg)


async def test_success_sends_once_and_completes(db_session, sample_user):
    order = await _paid_order(db_session)
    bot = FakeGiftBot()

    res = await gift_delivery.deliver(db_session, order.id, bot)

    assert res["success"] is True and res["handled"] is True
    assert res["outcome"] == "sent" and res["fulfilled"] is True
    assert bot.sent == [{"user_id": RECIPIENT_ID, "gift_id": "g15"}]
    o = await _reload(db_session, order.id)
    assert o.status == OrderStatus.COMPLETED
    assert o.fulfillment_status == "fulfilled"
    assert o.completed_at is not None
    assert o.fragment_payload == "telegram_sendGift:g15"
    state = await db_session.get(GiftSyncState, 1, populate_existing=True)
    assert state.bot_star_balance == 985
    notifs = (await db_session.execute(select(InAppNotification))).scalars().all()
    assert len(notifs) == 1 and notifs[0].user_id == BUYER_ID
    assert _to(bot, BUYER_ID)


async def test_second_call_is_skipped_and_sends_nothing(db_session, sample_user):
    order = await _paid_order(db_session)
    bot = FakeGiftBot()
    await gift_delivery.deliver(db_session, order.id, bot)

    res = await gift_delivery.deliver(db_session, order.id, bot)

    assert res["success"] is True and res["outcome"] == "skipped" and res["fulfilled"] is False
    assert len(bot.sent) == 1


async def test_already_claimed_order_is_skipped(db_session, sample_user):
    order = await _paid_order(db_session)
    order.fulfillment_status = "processing"
    await db_session.commit()
    bot = FakeGiftBot()

    res = await gift_delivery.deliver(db_session, order.id, bot)

    assert res["outcome"] == "skipped"
    assert bot.sent == []


async def test_concurrent_calls_send_once(db_session, sample_user):
    order = await _paid_order(db_session)

    class SlowBot(FakeGiftBot):
        async def send_gift(self, user_id, gift_id, **kw):
            await asyncio.sleep(0.01)  # let the other call run while "sending"
            return await super().send_gift(user_id=user_id, gift_id=gift_id, **kw)

    bot = SlowBot()
    make = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with make() as s1, make() as s2:
        results = await asyncio.gather(
            gift_delivery.deliver(s1, order.id, bot),
            gift_delivery.deliver(s2, order.id, bot),
        )

    assert len(bot.sent) == 1
    assert sorted(r["outcome"] for r in results) == ["sent", "skipped"]
    assert all(r["success"] for r in results)


async def test_unpaid_created_order_is_never_sent(db_session, sample_user):
    order = await _paid_order(db_session, payment_method="click")
    assert order.status == OrderStatus.CREATED
    bot = FakeGiftBot()

    res = await gift_delivery.deliver(db_session, order.id, bot)

    assert res["success"] is True and res["outcome"] == "skipped"
    assert bot.sent == []
    o = await _reload(db_session, order.id)
    assert o.status == OrderStatus.CREATED and o.fulfillment_status == "pending"


async def test_missing_order_is_skipped(db_session, sample_user):
    res = await gift_delivery.deliver(db_session, 424242, FakeGiftBot())
    assert res["success"] is True and res["outcome"] == "skipped"


async def test_bad_request_refunds_wallet_and_notifies(db_session, sample_user):
    order = await _paid_order(db_session)
    paid = await _wallet(db_session)
    bot = FakeGiftBot()
    bot.send_errors = [_bad("Bad Request: STARGIFT_INVALID")]

    res = await gift_delivery.deliver(db_session, order.id, bot)

    assert res["success"] is True and res["outcome"] == "refunded" and res["fulfilled"] is False
    assert bot.sent == []
    o = await _reload(db_session, order.id)
    assert o.status == OrderStatus.REFUNDED
    assert o.fulfillment_status == "failed"
    assert "STARGIFT_INVALID" in o.fulfillment_error
    assert await _wallet(db_session) == paid + Decimal(str(o.total_price))
    assert _to(bot, BUYER_ID), "buyer must be told"
    assert _to(bot, ADMIN_ID), "admins must be told"
    assert not any("Stars balansi yetmadi" in t for t in _to(bot, ADMIN_ID))

    # Repeated delivery must neither resend nor refund again.
    again = await gift_delivery.deliver(db_session, order.id, bot)
    assert again["outcome"] == "skipped"
    assert await _wallet(db_session) == paid + Decimal(str(o.total_price))


async def test_balance_error_alerts_admin_specially(db_session, sample_user):
    order = await _paid_order(db_session)
    bot = FakeGiftBot()
    bot.send_errors = [_bad("Bad Request: BALANCE_TOO_LOW")]

    res = await gift_delivery.deliver(db_session, order.id, bot)

    assert res["outcome"] == "refunded"
    admin_texts = _to(bot, ADMIN_ID)
    assert any("Botning Stars balansi yetmadi" in t and "BALANCE_TOO_LOW" in t for t in admin_texts)


async def test_forbidden_error_refunds(db_session, sample_user):
    order = await _paid_order(db_session)
    paid = await _wallet(db_session)
    bot = FakeGiftBot()
    bot.send_errors = [TelegramForbiddenError(method=METHOD, message="Forbidden: user blocked gifts")]

    res = await gift_delivery.deliver(db_session, order.id, bot)

    assert res["outcome"] == "refunded"
    o = await _reload(db_session, order.id)
    assert o.status == OrderStatus.REFUNDED
    assert await _wallet(db_session) == paid + Decimal(str(o.total_price))


async def test_retry_after_then_success(db_session, sample_user, sleeps):
    order = await _paid_order(db_session)
    bot = FakeGiftBot()
    bot.send_errors = [TelegramRetryAfter(method=METHOD, message="Too Many Requests", retry_after=3)]

    res = await gift_delivery.deliver(db_session, order.id, bot)

    assert res["outcome"] == "sent"
    assert sleeps == [3]
    assert len(bot.sent) == 1


async def test_retry_after_exhausted_goes_to_manual_review(db_session, sample_user, sleeps):
    order = await _paid_order(db_session)
    paid = await _wallet(db_session)
    bot = FakeGiftBot()
    bot.send_errors = [TelegramRetryAfter(method=METHOD, message="Too Many Requests", retry_after=1) for _ in range(3)]

    res = await gift_delivery.deliver(db_session, order.id, bot)

    assert res["success"] is True and res["outcome"] == "manual_review"
    assert len(sleeps) == gift_delivery.SEND_RETRY_MAX
    assert bot.sent == [] and bot.send_errors == []
    o = await _reload(db_session, order.id)
    assert o.fulfillment_status == "manual_review" and o.status == OrderStatus.PROCESSING
    assert await _wallet(db_session) == paid


async def test_retry_after_too_long_goes_to_manual_review(db_session, sample_user, sleeps):
    order = await _paid_order(db_session)
    bot = FakeGiftBot()
    bot.send_errors = [TelegramRetryAfter(method=METHOD, message="Too Many Requests", retry_after=31)]

    res = await gift_delivery.deliver(db_session, order.id, bot)

    assert res["outcome"] == "manual_review"
    assert sleeps == []
    assert bot.sent == []
    o = await _reload(db_session, order.id)
    assert o.fulfillment_status == "manual_review" and o.status == OrderStatus.PROCESSING


async def test_network_error_goes_to_manual_review_without_refund_or_resend(db_session, sample_user):
    order = await _paid_order(db_session)
    paid = await _wallet(db_session)
    bot = FakeGiftBot()
    bot.send_errors = [TelegramNetworkError(method=METHOD, message="Request timeout error")]

    res = await gift_delivery.deliver(db_session, order.id, bot)

    assert res["success"] is True and res["outcome"] == "manual_review"
    o = await _reload(db_session, order.id)
    assert o.status == OrderStatus.PROCESSING
    assert o.fulfillment_status == "manual_review"
    assert o.processing_at is not None
    assert await _wallet(db_session) == paid
    assert _to(bot, ADMIN_ID)

    again = await gift_delivery.deliver(db_session, order.id, bot)
    assert again["outcome"] == "skipped"
    assert bot.sent == []


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("boom"),
        TimeoutError(),
        TelegramServerError(method=METHOD, message="Internal Server Error"),
    ],
)
async def test_unknown_exception_goes_to_manual_review(db_session, sample_user, exc):
    order = await _paid_order(db_session)
    paid = await _wallet(db_session)
    bot = FakeGiftBot()
    bot.send_errors = [exc]

    res = await gift_delivery.deliver(db_session, order.id, bot)

    assert res["success"] is True and res["outcome"] == "manual_review"
    o = await _reload(db_session, order.id)
    assert o.status == OrderStatus.PROCESSING and o.fulfillment_status == "manual_review"
    assert await _wallet(db_session) == paid
    assert bot.sent == []


async def test_legacy_order_without_recipient_goes_to_manual_review(db_session, sample_user):
    order = await _paid_order(db_session)
    order.recipient_user_id = None
    await db_session.commit()
    bot = FakeGiftBot()

    res = await gift_delivery.deliver(db_session, order.id, bot)

    assert res["outcome"] == "manual_review"
    assert bot.sent == []
    o = await _reload(db_session, order.id)
    assert o.fulfillment_status == "manual_review"


async def test_notification_failures_do_not_break_delivery(db_session, sample_user):
    order = await _paid_order(db_session)

    class MuteBot(FakeGiftBot):
        async def send_message(self, chat_id, text, **kw):
            raise TelegramForbiddenError(method=METHOD, message="Forbidden: bot was blocked by the user")

    bot = MuteBot()
    bot.send_errors = [_bad("Bad Request: STARGIFT_INVALID")]
    paid = await _wallet(db_session)

    res = await gift_delivery.deliver(db_session, order.id, bot)

    assert res["outcome"] == "refunded"
    o = await _reload(db_session, order.id)
    assert o.status == OrderStatus.REFUNDED
    assert await _wallet(db_session) == paid + Decimal(str(o.total_price))


async def test_sweep_moves_stale_processing_to_manual_review(db_session, sample_user):
    fresh = await _paid_order(db_session)
    stale, _, _ = await OrderService.create_order(
        db_session, user_id=BUYER_ID, product_type="gift", item_title="g15", recipient_username=str(RECIPIENT_ID)
    )
    now = utc_now()
    for order, age in ((fresh, 4), (stale, 6)):
        order.status = OrderStatus.PROCESSING
        order.fulfillment_status = "processing"
        order.processing_at = now - timedelta(minutes=age)
    await db_session.commit()
    bot = FakeGiftBot()

    moved = await gift_delivery.sweep_stale_processing(db_session, bot, now=now)

    assert moved == 1
    assert (await _reload(db_session, fresh.id)).fulfillment_status == "processing"
    s = await _reload(db_session, stale.id)
    assert s.fulfillment_status == "manual_review" and s.status == OrderStatus.PROCESSING
    assert _to(bot, ADMIN_ID)
    assert bot.sent == []
    assert await gift_delivery.sweep_stale_processing(db_session, bot, now=now) == 0
