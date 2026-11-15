import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.web.security_headers import CSP_POLICY, LEGACY_CSP_EXEMPT
from app.web.server import ASSET_VERSION, app, build_app, render_index


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_legacy_app_page_has_no_csp_but_other_headers(client):
    assert "/app" in LEGACY_CSP_EXEMPT and "/admin" in LEGACY_CSP_EXEMPT
    r = await client.get("/app")
    assert "content-security-policy" not in r.headers
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"


async def test_non_legacy_paths_have_exact_csp(client):
    for path in ("/health", "/static/shared/tokens.css"):
        r = await client.get(path)
        assert r.headers["content-security-policy"] == CSP_POLICY
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"


async def test_static_code_is_revalidated(client):
    for path in ("/static/shared/tokens.css", "/static/user/app.js", "/static/user/screens/home.js"):
        r = await client.get(path)
        assert r.status_code == 200, path
        assert r.headers["cache-control"] == "no-cache", path


async def test_static_other_files_cached_for_a_day(client):
    r = await client.get("/static/shared/icons.svg")
    assert r.status_code == 200 and "max-age=86400" in r.headers["cache-control"]


async def test_static_js_conditional_get_returns_304(client):
    r = await client.get("/static/shared/dom.js")
    etag = r.headers["etag"]
    r2 = await client.get("/static/shared/dom.js", headers={"If-None-Match": etag})
    assert r2.status_code == 304


async def test_cors_rejects_foreign_origin(client):
    r = await client.get("/api/products", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


async def test_index_no_placeholder_and_no_cache(client):
    for path in ("/app", "/admin"):
        r = await client.get(path)
        assert r.status_code == 200
        assert "{{v}}" not in r.text
        assert r.headers["cache-control"] == "no-cache"


def test_render_index_substitutes_version(tmp_path):
    f = tmp_path / "index.html"
    f.write_text('<script src="/static/user/app.js?v={{v}}"></script>', encoding="utf-8")
    out = render_index(str(f))
    assert f"?v={ASSET_VERSION}" in out
    assert "{{v}}" not in out


def test_docs_disabled_in_production():
    prod = build_app(environment="production")
    assert prod.docs_url is None and prod.openapi_url is None
    assert build_app(environment="test").docs_url is not None
