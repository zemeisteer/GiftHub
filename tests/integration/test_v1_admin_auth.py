"""Every /api/v1/admin/* route must require an authenticated admin with a fitting permission."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.router import get_db as v1_get_db
from app.core.config import settings
from app.models.user import User
from app.web.server import app
from tests.conftest import make_telegram_init_data

REASON = {"reason": "test reason ok"}

# (method, path, json body)
ADMIN_ROUTES = [
    ("GET", "/api/v1/admin/reconciliation/dashboard", None),
    ("POST", "/api/v1/admin/reconciliation/audit", None),
    ("GET", "/api/v1/admin/reconciliation/discrepancies", None),
    ("POST", "/api/v1/admin/reconciliation/discrepancies/1/resolve", REASON),
    ("GET", "/api/v1/admin/dlq", None),
    ("POST", "/api/v1/admin/dlq/1/retry", None),
    ("POST", "/api/v1/admin/dlq/1/resolve", REASON),
    ("GET", "/api/v1/admin/providers", None),
    ("POST", "/api/v1/admin/providers/fragment/status", {**REASON, "status": "healthy"}),
    ("GET", "/api/v1/admin/feature-flags", None),
    ("POST", "/api/v1/admin/feature-flags/some_flag", {"is_enabled": True}),
    ("GET", "/api/v1/admin/catalog", None),
    (
        "POST",
        "/api/v1/admin/catalog",
        {"category": "stars", "sku": "x_1", "title": "X", "base_price_uzs": "1000"},
    ),
    ("GET", "/api/v1/admin/health/system", None),
    ("GET", "/api/v1/admin/orders/problematic", None),
    ("POST", "/api/v1/admin/orders/1/retry-fulfillment", REASON),
    ("POST", "/api/v1/admin/orders/1/manual-fulfill", REASON),
    ("POST", "/api/v1/admin/pricing/preview", {}),
]


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    # get_current_admin opens its own session; point it at the in-memory test DB.
    # (derive from db_session's engine: conftest may be imported under two module names)
    session_factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.web.auth.AsyncSessionLocal", session_factory)
    app.dependency_overrides[v1_get_db] = lambda: db_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(v1_get_db, None)


async def _make_user(db_session, uid, role):
    db_session.add(User(id=uid, username=f"u{uid}", first_name="T", role=role))
    await db_session.commit()


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
async def test_unauthenticated_rejected(client, method, path, body):
    r = await client.request(method, path, json=body)
    assert r.status_code in (401, 403), (method, path, r.status_code)


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
async def test_regular_user_with_init_data_rejected(client, db_session, method, path, body):
    await _make_user(db_session, 555001, "user")
    init = make_telegram_init_data(settings.BOT_TOKEN, 555001)
    r = await client.request(method, path, json=body, headers={"X-Telegram-Init-Data": init})
    assert r.status_code == 403, (method, path, r.status_code)


async def test_public_health_route_stays_public(client):
    r = await client.get("/api/v1/health/system")
    assert r.status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/health/system",
        "/api/v1/admin/orders/problematic",
        "/api/v1/admin/feature-flags",
    ],
)
async def test_super_admin_allowed(client, db_session, path):
    await _make_user(db_session, 555002, "super_admin")
    r = await client.get(path, headers={"X-Auth-User-Id": "555002"})
    assert r.status_code == 200, r.text


async def test_read_only_role_cannot_write(client, db_session):
    # price_admin has no settings.* permission at all
    await _make_user(db_session, 555003, "price_admin")
    h = {"X-Auth-User-Id": "555003"}
    r = await client.post("/api/v1/admin/feature-flags/maintenance", json={"is_enabled": True}, headers=h)
    assert r.status_code == 403
    r = await client.get("/api/v1/admin/feature-flags", headers=h)
    assert r.status_code == 403
    # but its own read permission works
    r = await client.get("/api/v1/admin/orders/problematic", headers=h)
    assert r.status_code == 200
    r = await client.post("/api/v1/admin/orders/1/manual-fulfill", json=REASON, headers=h)
    assert r.status_code == 403


async def test_dlq_resolve_records_real_admin_id(client, db_session, monkeypatch):
    await _make_user(db_session, 555004, "super_admin")
    seen = {}

    async def fake_resolve(session, job_id, admin_id, notes):
        seen["admin_id"] = admin_id
        return object()

    monkeypatch.setattr("app.api.v1.router.dlq_service.resolve_job", fake_resolve)
    r = await client.post("/api/v1/admin/dlq/1/resolve", json=REASON, headers={"X-Auth-User-Id": "555004"})
    assert r.status_code == 200
    assert seen["admin_id"] == 555004
