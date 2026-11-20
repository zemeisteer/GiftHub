from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.router import get_db as v1_get_db
from app.core.config import settings
from app.models.gift import GiftSyncState, TelegramGift
from app.models.order import Order, OrderStatus
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.services import fragment as fragment_module
from app.services import gift_jobs, worker
from app.services.fulfillment.service import fulfillment_service
from app.services.orders.service import OrderService
from app.web.server import app
from tests.gift_fakes import FakeGiftBot

BUYER_ID = 12345678  # sample_user
RECIPIENT_ID = 987654321
ADMIN_ID = 777000111
REASON = {"reason": "test reason ok"}


@pytest.fixture(autouse=True)
def _admins(monkeypatch):
    monkeypatch.setattr(settings, "ADMINS", [ADMIN_ID])


async def _paid_gift(db_session) -> Order:
    if await db_session.get(TelegramGift, "g15") is None:
        db_session.add(TelegramGift(id="g15", star_count=15))
        db_session.add(GiftSyncState(id=1, bot_star_balance=1000))
        await db_session.commit()
    order, _, _ = await OrderService.create_order(
        db_session,
        user_id=BUYER_ID,
        product_type="gift",
        item_title="g15",
        recipient_username=str(RECIPIENT_ID),
        payment_method="balance",
    )
    return order


async def _reload(db_session, order_id) -> Order:
    return await db_session.get(Order, order_id, populate_existing=True)


# ---------------------------------------------------------------- routing


async def test_fulfill_order_automated_routes_gift_to_delivery(db_session, sample_user, monkeypatch):
    order = await _paid_gift(db_session)

    async def boom(*a, **kw):
        raise AssertionError("Fragment must not be used for gifts")

    monkeypatch.setattr(fragment_module.fragment_client, "fulfill_order", boom)
    bot = FakeGiftBot()

    res = await fulfillment_service.fulfill_order_automated(db_session, order.id, bot=bot)

    assert res["success"] is True and res["outcome"] == "sent"
    assert len(bot.sent) == 1
    assert (await _reload(db_session, order.id)).fulfillment_status == "fulfilled"


async def test_fragment_fulfill_order_routes_gift_to_delivery(db_session, sample_user, monkeypatch):
    order = await _paid_gift(db_session)
    factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(fragment_module, "AsyncSessionLocal", factory)

    async def boom(*a, **kw):
        raise AssertionError("no Fragment invoice for gifts")

    monkeypatch.setattr(fragment_module.fragment_client, "create_stars_invoice", boom)
    bot = FakeGiftBot()

    res = await fragment_module.fragment_client.fulfill_order(order_id=order.id, bot=bot)

    assert res["outcome"] == "sent"
    assert len(bot.sent) == 1


async def test_outbox_event_for_gift_is_marked_processed_even_after_refund(db_session, sample_user):
    order = await _paid_gift(db_session)
    bot = FakeGiftBot()
    bot.balance = 0  # catalog balance too low is not enough: force a definite Telegram rejection
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import SendGift

    bot.send_errors = [
        TelegramBadRequest(method=SendGift(gift_id="g15", user_id=RECIPIENT_ID), message="USER_DISALLOWED")
    ]
    ev = (
        await db_session.execute(
            OutboxEvent.__table__.select().where(OutboxEvent.event_type == "ORDER_FULFILLMENT_REQUESTED")
        )
    ).first()
    assert ev is not None

    await worker.process_outbox_events_cycle(session=db_session, bot=bot)

    refreshed = await _reload(db_session, order.id)
    assert refreshed.status == OrderStatus.REFUNDED.value
    ev_after = await db_session.get(OutboxEvent, ev.id, populate_existing=True)
    assert ev_after.status == "processed"


# ---------------------------------------------------------------- admin routes


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.web.auth.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.web.routes.admin.orders.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.web.routes.admin.orders.get_bot", lambda: FakeGiftBot())
    app.dependency_overrides[v1_get_db] = lambda: db_session
    db_session.add(User(id=555002, username="sa", first_name="S", role="super_admin"))
    await db_session.commit()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(v1_get_db, None)


HDR = {"X-Auth-User-Id": "555002"}


async def test_admin_retry_endpoints_return_409_for_gift_orders(client, db_session, sample_user):
    order = await _paid_gift(db_session)
    for state in ("pending", "processing", "manual_review"):
        order.fulfillment_status = state
        await db_session.commit()
        for path, body in (
            (f"/api/v1/admin/orders/{order.id}/retry-fulfillment", REASON),
            (f"/api/admin/orders/{order.id}/retry-fulfillment", None),
            (f"/api/admin/orders/{order.id}/fulfill-fragment", None),
        ):
            r = await client.post(path, json=body, headers=HDR)
            assert r.status_code == 409, (state, path, r.status_code, r.text)
            assert "sovg'alar tarixini" in r.text
        o = await _reload(db_session, order.id)
        assert o.fulfillment_status == state
        assert o.status == OrderStatus.PAID.value


async def test_admin_money_and_status_actions_blocked_while_gift_processing(client, db_session, sample_user):
    order = await _paid_gift(db_session)
    order.fulfillment_status = "processing"
    await db_session.commit()
    balance_before = (await db_session.get(User, BUYER_ID, populate_existing=True)).balance

    calls = [
        (f"/api/v1/admin/orders/{order.id}/manual-fulfill", REASON),
        (f"/api/admin/orders/{order.id}/refund", REASON),
        (f"/api/admin/orders/{order.id}/mark-fulfilled", None),
        (f"/api/admin/orders/{order.id}/status", {"status": "cancel", "reason": "cancel reason"}),
        (f"/api/admin/orders/{order.id}/status", {"status": "done"}),
    ]
    for path, body in calls:
        r = await client.post(path, json=body, headers=HDR)
        assert r.status_code == 409, (path, r.status_code, r.text)
        assert "yetkazilmoqda" in r.text

    o = await _reload(db_session, order.id)
    assert o.status == OrderStatus.PAID.value and o.fulfillment_status == "processing"
    assert (await db_session.get(User, BUYER_ID, populate_existing=True)).balance == balance_before


async def test_manual_fulfill_and_refund_still_work_for_gift_in_manual_review(client, db_session, sample_user):
    order = await _paid_gift(db_session)
    order.fulfillment_status = "manual_review"
    await db_session.commit()

    r = await client.post(f"/api/v1/admin/orders/{order.id}/manual-fulfill", json=REASON, headers=HDR)
    assert r.status_code == 200, r.text
    assert (await _reload(db_session, order.id)).status == OrderStatus.COMPLETED.value

    order2 = await _paid_gift(db_session)
    order2.fulfillment_status = "manual_review"
    await db_session.commit()
    r = await client.post(f"/api/admin/orders/{order2.id}/refund", json=REASON, headers=HDR)
    assert r.status_code == 200, r.text
    assert (await _reload(db_session, order2.id)).status == OrderStatus.REFUNDED.value


# ---------------------------------------------------------------- maintenance


@pytest.fixture
def jobs(monkeypatch):
    calls: list[str] = []

    @asynccontextmanager
    async def scope():
        yield object()

    async def sweep(session, bot, now=None):
        calls.append("sweep")
        return 0

    async def sync(session, bot):
        calls.append("sync")
        return {}

    monkeypatch.setattr(gift_jobs, "async_session_scope", scope)
    monkeypatch.setattr(gift_jobs.gift_delivery, "sweep_stale_processing", sweep)
    monkeypatch.setattr(gift_jobs.gift_catalog, "sync", sync)
    return calls


async def test_run_gift_maintenance_schedule(jobs):
    await gift_jobs.run_gift_maintenance(object(), 7)
    assert jobs == []
    await gift_jobs.run_gift_maintenance(object(), 150)
    assert jobs == ["sweep"]
    jobs.clear()
    await gift_jobs.run_gift_maintenance(object(), 1800)
    assert jobs == ["sweep", "sync"]


async def test_maintenance_swallows_errors(monkeypatch):
    @asynccontextmanager
    async def scope():
        yield object()

    async def boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(gift_jobs, "async_session_scope", scope)
    monkeypatch.setattr(gift_jobs.gift_delivery, "sweep_stale_processing", boom)
    monkeypatch.setattr(gift_jobs.gift_catalog, "sync", boom)
    monkeypatch.setattr(gift_jobs.gift_catalog, "sync_if_empty", boom)

    await gift_jobs.run_gift_maintenance(object(), 1800)
    await gift_jobs.startup_gift_sync(object())
