"""Non-admin /api/v1 user routes must authenticate the caller via Telegram initData
and never act on a client-supplied user_id that differs from the caller."""

from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.router import get_db as v1_get_db
from app.core.config import settings
from app.models.order import Order
from app.models.recipient import SavedRecipient
from app.models.user import User
from app.web.server import app
from tests.conftest import make_telegram_init_data

USER_A = 7100001
USER_B = 7100002
ADMIN = 7100009
ORDER_B_CODE = "GH-AUTHB01"


def _hdr(uid: int) -> dict:
    return {"X-Telegram-Init-Data": make_telegram_init_data(settings.BOT_TOKEN, uid)}


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    # Behave like production: no dev/test fallback identity without valid initData.
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    session_factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.web.auth.AsyncSessionLocal", session_factory)
    app.dependency_overrides[v1_get_db] = lambda: db_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(v1_get_db, None)


@pytest_asyncio.fixture
async def seeded(db_session):
    db_session.add_all(
        [
            User(id=USER_A, username="usera", first_name="A", role="user", balance=Decimal("500000.00")),
            User(id=USER_B, username="userb", first_name="B", role="user", balance=Decimal("500000.00")),
            User(id=ADMIN, username="adm", first_name="Adm", role="super_admin", balance=Decimal("0")),
        ]
    )
    await db_session.commit()
    order = Order(
        order_code=ORDER_B_CODE,
        user_id=USER_B,
        product_type="stars",
        item_title="100 Stars",
        amount=100,
        unit_price=Decimal("180.00"),
        total_price=Decimal("18000.00"),
        cost_price=Decimal("15000.00"),
        margin=Decimal("3000.00"),
        payment_method="balance",
        status="completed",
        recipient_username="userb",
    )
    rec = SavedRecipient(user_id=USER_B, recipient_username="friendofb", label="friend")
    db_session.add_all([order, rec])
    await db_session.commit()
    await db_session.refresh(order)
    await db_session.refresh(rec)
    return {"order_id": order.id, "recipient_id": rec.id}


async def _balance(db_session, uid) -> Decimal:
    db_session.expire_all()
    return (await db_session.execute(select(User.balance).where(User.id == uid))).scalar_one()


def _routes(seeded):
    rid = seeded["recipient_id"]
    return [
        ("POST", "/api/v1/orders/checkout", {"user_id": USER_B, "product_type": "stars", "quantity": 100}),
        ("GET", f"/api/v1/orders/{ORDER_B_CODE}/timeline", None),
        ("GET", f"/api/v1/orders/{ORDER_B_CODE}/receipt", None),
        ("GET", f"/api/v1/orders/{ORDER_B_CODE}/buy-again-details", None),
        ("GET", f"/api/v1/recipients?user_id={USER_B}", None),
        ("POST", "/api/v1/recipients", {"user_id": USER_B, "recipient_username": "x"}),
        ("DELETE", f"/api/v1/recipients/{rid}?user_id={USER_B}", None),
    ]


async def test_unauthenticated_rejected(client, db_session, seeded):
    before = await _balance(db_session, USER_B)
    for method, path, body in _routes(seeded):
        r = await client.request(method, path, json=body)
        assert r.status_code in (401, 403), (method, path, r.status_code)
    assert await _balance(db_session, USER_B) == before
    assert len((await db_session.execute(select(Order).where(Order.user_id == USER_B))).scalars().all()) == 1


async def test_invalid_init_data_rejected(client, seeded):
    bad = {"X-Telegram-Init-Data": make_telegram_init_data("wrong-token-xxxxxxxxxxxxxxxx", USER_B)}
    for method, path, body in _routes(seeded):
        r = await client.request(method, path, json=body, headers=bad)
        assert r.status_code in (401, 403), (method, path, r.status_code)


async def test_cannot_checkout_as_another_user(client, db_session, seeded):
    before_a = await _balance(db_session, USER_A)
    before_b = await _balance(db_session, USER_B)
    r = await client.post(
        "/api/v1/orders/checkout",
        json={"user_id": USER_B, "product_type": "stars", "quantity": 100},
        headers=_hdr(USER_A),
    )
    assert r.status_code == 403
    assert await _balance(db_session, USER_A) == before_a
    assert await _balance(db_session, USER_B) == before_b
    orders = (await db_session.execute(select(Order))).scalars().all()
    assert len(orders) == 1


async def test_checkout_as_self_uses_caller(client, db_session, seeded):
    before = await _balance(db_session, USER_A)
    r = await client.post(
        "/api/v1/orders/checkout",
        json={"product_type": "stars", "quantity": 100},
        headers=_hdr(USER_A),
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    order = (await db_session.execute(select(Order).where(Order.id == r.json()["order"]["id"]))).scalar_one()
    assert order.user_id == USER_A
    assert await _balance(db_session, USER_A) < before


@pytest.mark.parametrize("suffix", ["timeline", "receipt", "buy-again-details"])
async def test_other_users_order_is_404(client, seeded, suffix):
    r = await client.get(f"/api/v1/orders/{ORDER_B_CODE}/{suffix}", headers=_hdr(USER_A))
    assert r.status_code == 404
    # also by numeric id
    r = await client.get(f"/api/v1/orders/{seeded['order_id']}/{suffix}", headers=_hdr(USER_A))
    assert r.status_code == 404


@pytest.mark.parametrize("suffix", ["timeline", "receipt", "buy-again-details"])
async def test_owner_can_read_order(client, seeded, suffix):
    r = await client.get(f"/api/v1/orders/{ORDER_B_CODE}/{suffix}", headers=_hdr(USER_B))
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True


async def test_owner_receipt_hides_internal_financials(client, seeded):
    r = await client.get(f"/api/v1/orders/{ORDER_B_CODE}/receipt", headers=_hdr(USER_B))
    receipt = r.json()["receipt"]
    assert "cost_price_uzs" not in receipt["financials"]
    assert "margin_uzs" not in receipt["financials"]
    assert "provider_tx_id" not in receipt["payment"]
    assert receipt["financials"]["total_price_uzs"] == 18000.0
    assert receipt["receipt_number"] == ORDER_B_CODE


async def test_admin_can_read_any_receipt_with_internals(client, seeded):
    r = await client.get(f"/api/v1/orders/{ORDER_B_CODE}/receipt", headers=_hdr(ADMIN))
    assert r.status_code == 200
    receipt = r.json()["receipt"]
    assert receipt["financials"]["cost_price_uzs"] == 15000.0
    assert receipt["financials"]["margin_uzs"] == 3000.0
    assert "provider_tx_id" in receipt["payment"]


async def test_recipients_list_other_user_forbidden(client, seeded):
    r = await client.get(f"/api/v1/recipients?user_id={USER_B}", headers=_hdr(USER_A))
    assert r.status_code == 403


async def test_recipients_list_own(client, seeded):
    r = await client.get(f"/api/v1/recipients?user_id={USER_B}", headers=_hdr(USER_B))
    assert r.status_code == 200
    assert [x["recipient_username"] for x in r.json()["recipients"]] == ["friendofb"]
    # user_id is optional: derived from the caller
    r = await client.get("/api/v1/recipients", headers=_hdr(USER_A))
    assert r.status_code == 200
    assert r.json()["recipients"] == []


async def test_recipients_add_as_other_user_forbidden(client, db_session, seeded):
    r = await client.post(
        "/api/v1/recipients", json={"user_id": USER_B, "recipient_username": "evil"}, headers=_hdr(USER_A)
    )
    assert r.status_code == 403
    rows = (await db_session.execute(select(SavedRecipient).where(SavedRecipient.recipient_username == "evil"))).all()
    assert rows == []


async def test_recipients_add_own(client, db_session, seeded):
    r = await client.post(
        "/api/v1/recipients", json={"user_id": USER_A, "recipient_username": "@pal"}, headers=_hdr(USER_A)
    )
    assert r.status_code == 200, r.text
    r = await client.post("/api/v1/recipients", json={"recipient_username": "pal2"}, headers=_hdr(USER_A))
    assert r.status_code == 200, r.text
    db_session.expire_all()
    names = (
        (await db_session.execute(select(SavedRecipient.recipient_username).where(SavedRecipient.user_id == USER_A)))
        .scalars()
        .all()
    )
    assert sorted(names) == ["pal", "pal2"]


async def test_recipients_delete_other_users(client, db_session, seeded):
    rid = seeded["recipient_id"]
    # spoofed user_id param
    r = await client.delete(f"/api/v1/recipients/{rid}?user_id={USER_B}", headers=_hdr(USER_A))
    assert r.status_code == 403
    # no user_id param: B's record isn't A's
    r = await client.delete(f"/api/v1/recipients/{rid}", headers=_hdr(USER_A))
    assert r.status_code == 404
    db_session.expire_all()
    assert await db_session.get(SavedRecipient, rid) is not None


async def test_recipients_delete_own(client, db_session, seeded):
    rid = seeded["recipient_id"]
    r = await client.delete(f"/api/v1/recipients/{rid}?user_id={USER_B}", headers=_hdr(USER_B))
    assert r.status_code == 200
    db_session.expire_all()
    assert await db_session.get(SavedRecipient, rid) is None


async def test_public_catalog_stays_public(client):
    r = await client.get("/api/v1/catalog")
    assert r.status_code == 200
