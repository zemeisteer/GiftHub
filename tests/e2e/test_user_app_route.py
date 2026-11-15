import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.web.security_headers import CSP_POLICY, LEGACY_CSP_EXEMPT
from app.web.server import ASSET_VERSION, app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_new_user_app_is_served_with_strict_csp(client):
    assert "/app/new" not in LEGACY_CSP_EXEMPT
    r = await client.get("/app/new")
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == CSP_POLICY
    assert r.headers["cache-control"] == "no-cache"
    assert "{{v}}" not in r.text
    assert f"/static/user/app.js?v={ASSET_VERSION}" in r.text
    assert 'id="outlet"' in r.text


async def test_new_user_app_assets_are_served(client):
    for path in ("/static/user/app.js", "/static/user/app.css", "/static/user/screens/home.js", "/static/user/screens/state.js"):
        r = await client.get(path)
        assert r.status_code == 200, path
