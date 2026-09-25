import pytest
from httpx import ASGITransport, AsyncClient

from app.web.server import app


@pytest.mark.asyncio
async def test_health_and_ready_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["status"] == "healthy"
        assert health_resp.json()["app"] == "GiftHub"

        ready_resp = await client.get("/ready")
        assert ready_resp.status_code == 200
        assert ready_resp.json()["status"] in ["ready", "degraded"]


@pytest.mark.asyncio
async def test_api_products_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/products")
        assert resp.status_code == 200
        data = resp.json()
        assert "stars_packages" in data


@pytest.mark.asyncio
async def test_api_admin_stats_unauthorized():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Request without any credentials
        resp = await client.get("/api/admin/stats")
        assert resp.status_code in [401, 403]
