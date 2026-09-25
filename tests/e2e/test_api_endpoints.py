import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.web.server import app


@pytest.mark.asyncio
async def test_health_and_ready_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Liveness probes
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["status"] == "healthy"
        assert health_resp.json()["app"] == "GiftHub"

        live_resp = await client.get("/health/live")
        assert live_resp.status_code == 200
        assert live_resp.json()["status"] == "healthy"

        # Readiness probes
        ready_resp = await client.get("/ready")
        assert ready_resp.status_code == 200
        assert ready_resp.json()["status"] in ["ready", "degraded"]

        ready_v2 = await client.get("/health/ready")
        assert ready_v2.status_code == 200
        assert ready_v2.json()["status"] in ["ready", "degraded"]


@pytest.mark.asyncio
async def test_api_products_endpoint(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/products")
            assert resp.status_code == 200
            data = resp.json()
            assert "stars_packages" in data
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_api_admin_stats_unauthorized():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Request without any credentials
        resp = await client.get("/api/admin/stats")
        assert resp.status_code in [401, 403]
