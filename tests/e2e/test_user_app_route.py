import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.web.security_headers import CSP_POLICY
from app.web.server import ASSET_VERSION, app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_user_app_is_served_with_strict_csp(client):
    r = await client.get("/app")
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == CSP_POLICY
    assert r.headers["cache-control"] == "no-cache"
    assert "{{v}}" not in r.text
    assert f"/static/user/app.js?v={ASSET_VERSION}" in r.text
    assert 'id="outlet"' in r.text


async def test_old_preview_route_is_gone(client):
    r = await client.get("/app/new")
    assert r.status_code == 404


async def test_user_app_assets_are_served(client):
    for path in (
        "/static/user/app.js",
        "/static/user/app.css",
        "/static/user/store.js",
        "/static/user/screens/home.js",
        "/static/shared/state.js",
        "/static/user/screens/orders.js",
        "/static/user/screens/referral.js",
        "/static/user/screens/profile.js",
        "/static/user/screens/gate.js",
    ):
        r = await client.get(path)
        assert r.status_code == 200, path


async def test_root_page_has_no_inline_style(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "<style" not in r.text.lower()
    assert 'style="' not in r.text.lower()
    css = await client.get("/static/shared/landing.css")
    assert css.status_code == 200


async def test_static_does_not_serve_test_files(client):
    assert (await client.get("/static/shared/api.test.mjs")).status_code == 404
    assert (await client.get("/static/admin/views.test.mjs")).status_code == 404
    assert (await client.get("/static/node_modules/x.js")).status_code == 404
    assert (await client.get("/static/shared/api.js")).status_code == 200
