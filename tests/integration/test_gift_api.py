"""Public gift catalog in /api/products and the admin gifts API."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import get_db
from app.core.security import ROLE_PERMISSIONS, Permission
from app.models.audit import AdminAuditLog
from app.models.gift import GiftSyncState, TelegramGift
from app.models.user import User
from app.web import state
from app.web.server import app
from tests.gift_fakes import FakeGiftBot, make_gift

BIG_ID = "5170145012310081615"
ADMIN_ID = 880001
READER_ID = 880002
USER_ID = 880003


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.web.auth.AsyncSessionLocal", factory)
    monkeypatch.setitem(ROLE_PERMISSIONS, "pricing_viewer", {Permission.PRICING_READ})
    app.dependency_overrides[get_db] = lambda: db_session
    db_session.add_all(
        [
            User(id=ADMIN_ID, username="adm", first_name="A", role="super_admin"),
            User(id=READER_ID, username="rdr", first_name="R", role="pricing_viewer"),
            User(id=USER_ID, username="usr", first_name="U", role="user"),
        ]
    )
    await db_session.commit()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


def _h(uid):
    return {"X-Auth-User-Id": str(uid)}


async def _seed(db_session, balance=1000):
    db_session.add_all(
        [
            TelegramGift(id=BIG_ID, star_count=15, emoji="🧸", price_override_uzs=99999),
            TelegramGift(id="g50", star_count=50, emoji="🌹"),
            TelegramGift(id="gOff", star_count=25, enabled=False),
            GiftSyncState(id=1, bot_star_balance=balance),
        ]
    )
    await db_session.commit()


async def _admin_list(client):
    return (await client.get("/api/admin/gifts", headers=_h(ADMIN_ID))).json()


async def test_public_products_gifts_from_catalog_without_cost(client, db_session):
    await _seed(db_session)
    r = await client.get("/api/products")
    gifts = r.json()["gifts"]
    assert {g["id"] for g in gifts} == {BIG_ID, "g50"}
    for g in gifts:
        assert "cost_uzs" not in g and "price_override_uzs" not in g
    assert "price_override_uzs" not in r.text
    assert '"cost_uzs"' not in r.text


async def test_gift_id_is_returned_as_string_without_precision_loss(client, db_session):
    await _seed(db_session)
    pub = await client.get("/api/products")
    assert next(g for g in pub.json()["gifts"] if g["stars"] == 15)["id"] == BIG_ID
    assert f'"id":"{BIG_ID}"' in pub.text.replace(" ", "")
    adm = await client.get("/api/admin/gifts", headers=_h(ADMIN_ID))
    assert f'"id":"{BIG_ID}"' in adm.text.replace(" ", "")
    assert all(isinstance(g["id"], str) for g in adm.json()["gifts"])


async def test_admin_gifts_requires_permission(client, db_session):
    await _seed(db_session)
    for uid in (None, USER_ID):
        h = _h(uid) if uid else {}
        assert (await client.get("/api/admin/gifts", headers=h)).status_code in (401, 403)
        r = await client.patch("/api/admin/gifts/g50", json={"enabled": False}, headers=h)
        assert r.status_code in (401, 403)
        assert (await client.post("/api/admin/gifts/sync", headers=h)).status_code in (401, 403)
    assert (await client.get("/api/admin/gifts", headers=_h(READER_ID))).status_code == 200
    r = await client.patch("/api/admin/gifts/g50", json={"enabled": False}, headers=_h(READER_ID))
    assert r.status_code == 403
    assert (await client.post("/api/admin/gifts/sync", headers=_h(READER_ID))).status_code == 403
    assert (await db_session.get(TelegramGift, "g50", populate_existing=True)).enabled is True


async def test_admin_list_shape_and_low_balance_flag(client, db_session):
    await _seed(db_session, balance=1000)
    data = await _admin_list(client)
    assert set(data) == {
        "gifts",
        "bot_star_balance",
        "reserved_stars",
        "last_sync_at",
        "last_sync_error",
        "low_balance",
    }
    assert data["bot_star_balance"] == 1000 and data["reserved_stars"] == 0
    assert data["low_balance"] is False
    g = next(x for x in data["gifts"] if x["id"] == BIG_ID)
    assert set(g) == {
        "id",
        "emoji",
        "title",
        "name",
        "star_count",
        "price_uzs",
        "cost_uzs",
        "price_override_uzs",
        "enabled",
        "available",
        "is_limited",
        "remaining_count",
        "is_premium",
        "synced_at",
    }
    assert g["price_uzs"] == 99999 and g["price_override_uzs"] == 99999 and g["cost_uzs"] > 0
    row = await db_session.get(GiftSyncState, 1)
    row.bot_star_balance = 99  # below the 100 floor
    await db_session.commit()
    assert (await _admin_list(client))["low_balance"] is True
    row.bot_star_balance = 120
    await db_session.commit()
    assert (await _admin_list(client))["low_balance"] is False
    row.bot_star_balance = None
    await db_session.commit()
    d = await _admin_list(client)
    assert d["bot_star_balance"] is None and d["low_balance"] is False


async def test_low_balance_when_below_cheapest_enabled_gift(client, db_session):
    db_session.add_all([TelegramGift(id="exp", star_count=500), GiftSyncState(id=1, bot_star_balance=300)])
    await db_session.commit()
    assert (await _admin_list(client))["low_balance"] is True


async def test_patch_toggle_title_override(client, db_session):
    await _seed(db_session)
    r = await client.patch(
        "/api/admin/gifts/g50",
        json={"enabled": False, "title": "Atirgul", "price_override_uzs": 500000},
        headers=_h(ADMIN_ID),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False and body["title"] == "Atirgul" and body["price_override_uzs"] == 500000
    row = await db_session.get(TelegramGift, "g50", populate_existing=True)
    assert row.enabled is False and row.title == "Atirgul" and float(row.price_override_uzs) == 500000
    logs = (await db_session.execute(select(AdminAuditLog))).scalars().all()
    assert len(logs) == 1 and logs[0].entity_id == "g50" and logs[0].admin_id == ADMIN_ID
    # absent fields stay untouched
    r = await client.patch("/api/admin/gifts/g50", json={"enabled": True}, headers=_h(ADMIN_ID))
    assert r.json()["title"] == "Atirgul" and r.json()["price_override_uzs"] == 500000


async def test_override_below_cost_rejected(client, db_session):
    await _seed(db_session)
    r = await client.patch("/api/admin/gifts/g50", json={"price_override_uzs": 1}, headers=_h(ADMIN_ID))
    assert r.status_code == 400
    assert (await db_session.get(TelegramGift, "g50", populate_existing=True)).price_override_uzs is None
    assert (await db_session.execute(select(AdminAuditLog))).scalars().all() == []
    # judged against the pure cost, not the gift's current override
    gifts = (await _admin_list(client))["gifts"]
    cost = next(g for g in gifts if g["id"] == BIG_ID)["cost_uzs"]
    assert cost > 1
    path = f"/api/admin/gifts/{BIG_ID}"
    r = await client.patch(path, json={"price_override_uzs": cost - 1}, headers=_h(ADMIN_ID))
    assert r.status_code == 400
    r = await client.patch(path, json={"price_override_uzs": cost + 1}, headers=_h(ADMIN_ID))
    assert r.status_code == 200


async def test_override_null_clears(client, db_session):
    await _seed(db_session)
    await client.patch("/api/admin/gifts/g50", json={"title": "X"}, headers=_h(ADMIN_ID))
    path = f"/api/admin/gifts/{BIG_ID}"
    r = await client.patch(path, json={"price_override_uzs": None}, headers=_h(ADMIN_ID))
    assert r.status_code == 200 and r.json()["price_override_uzs"] is None
    assert (await db_session.get(TelegramGift, BIG_ID, populate_existing=True)).price_override_uzs is None
    r = await client.patch("/api/admin/gifts/g50", json={"title": None}, headers=_h(ADMIN_ID))
    assert r.json()["title"] is None and r.json()["name"] == "50 ⭐ sovg'a"


async def test_patch_unknown_gift_404(client, db_session):
    r = await client.patch("/api/admin/gifts/nope", json={"enabled": False}, headers=_h(ADMIN_ID))
    assert r.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"title": "x" * 65},
        {"price_override_uzs": -1},
        {"price_override_uzs": 1e12},
        {"price_override_uzs": "abc"},
        {"enabled": "maybe"},
    ],
)
async def test_patch_validation(client, db_session, body):
    await _seed(db_session)
    r = await client.patch("/api/admin/gifts/g50", json=body, headers=_h(ADMIN_ID))
    assert r.status_code == 422, r.text


async def test_sync_endpoint_success_and_logged(client, db_session, monkeypatch):
    monkeypatch.setattr(state, "bot_instance", FakeGiftBot([make_gift("a1", 15)], balance=500))
    r = await client.post("/api/admin/gifts/sync", headers=_h(ADMIN_ID))
    assert r.status_code == 200 and r.json()["added"] == 1
    assert len((await db_session.execute(select(AdminAuditLog))).scalars().all()) == 1


async def test_sync_endpoint_without_bot_503_and_telegram_error_502(client, db_session, monkeypatch):
    monkeypatch.setattr(state, "bot_instance", None)
    assert (await client.post("/api/admin/gifts/sync", headers=_h(ADMIN_ID))).status_code == 503

    class Boom(FakeGiftBot):
        async def get_available_gifts(self, **kw):
            raise RuntimeError("bot123456:SECRET-TOKEN exploded")

    monkeypatch.setattr(state, "bot_instance", Boom())
    r = await client.post("/api/admin/gifts/sync", headers=_h(ADMIN_ID))
    assert r.status_code == 502
    assert "SECRET" not in r.text and "RuntimeError" not in r.text
