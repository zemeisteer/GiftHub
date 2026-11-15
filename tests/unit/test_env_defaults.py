import pytest
from httpx import ASGITransport, AsyncClient

import tunnel
from app.core.config import settings
from app.web.server import app


def test_environment_defaults_to_production(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    from app.core.config import Settings

    assert Settings(_env_file=None).ENVIRONMENT == "production"


async def test_auth_user_id_rejected_in_production(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/user/me", params={"auth_user_id": 1})
    assert r.status_code == 401


def test_tunnel_refuses_development(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    with pytest.raises(SystemExit):
        tunnel.ensure_not_development()
