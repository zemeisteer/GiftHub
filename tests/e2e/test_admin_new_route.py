import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.web.auth import get_current_admin
from app.web.security_headers import CSP_POLICY, LEGACY_CSP_EXEMPT
from app.web.server import ASSET_VERSION, app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class _Admin:
    def __init__(self, role, uid=999001):
        self.id = uid
        self.role = role
        self.first_name = "Ali"
        self.username = "ali"


async def test_admin_new_is_served_with_strict_csp(client):
    assert "/admin/new" not in LEGACY_CSP_EXEMPT
    r = await client.get("/admin/new")
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == CSP_POLICY
    assert r.headers["cache-control"] == "no-cache"
    assert "{{v}}" not in r.text
    assert f"/static/admin/admin.js?v={ASSET_VERSION}" in r.text
    assert 'id="outlet"' in r.text


async def test_legacy_admin_still_served_without_csp(client):
    r = await client.get("/admin")
    assert r.status_code == 200
    assert "content-security-policy" not in r.headers


async def test_admin_assets_are_served(client):
    for name in ("admin.js", "admin.css", "nav.js", "confirm.js", "registry.js"):
        r = await client.get(f"/static/admin/{name}")
        assert r.status_code == 200, name


async def test_admin_me_requires_admin(client):
    r = await client.get("/api/admin/me")
    assert r.status_code in (401, 403)


async def test_admin_me_returns_permission_names(client):
    app.dependency_overrides[get_current_admin] = lambda: _Admin("price_admin")
    try:
        r = await client.get("/api/admin/me")
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
    assert r.status_code == 200
    data = r.json()
    assert data["role"] == "price_admin"
    assert data["permissions"] == ["ANALYTICS_READ", "ORDERS_READ", "PRICING_READ", "PRICING_UPDATE"]


async def test_admin_me_super_admin_has_all(client):
    app.dependency_overrides[get_current_admin] = lambda: _Admin("super_admin")
    try:
        r = await client.get("/api/admin/me")
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
    perms = r.json()["permissions"]
    assert "ADMINS_MANAGE" in perms and "SETTINGS_UPDATE" in perms and len(perms) == 16
