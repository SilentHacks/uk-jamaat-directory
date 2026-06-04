from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.main import create_app


@pytest.mark.asyncio
async def test_admin_endpoint_is_unavailable_without_configured_key() -> None:
    app = create_app(Settings(allowed_hosts=["test"], admin_api_key=None))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/admin/health", headers={"X-Request-ID": "admin-test"})

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "service_unavailable",
            "message": "Admin API is not configured",
            "request_id": "admin-test",
        }
    }


@pytest.mark.asyncio
async def test_admin_endpoint_rejects_invalid_key() -> None:
    app = create_app(Settings(allowed_hosts=["test"], admin_api_key="secret"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/admin/health", headers={"X-Admin-Key": "wrong"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_admin_endpoint_accepts_valid_key() -> None:
    app = create_app(Settings(allowed_hosts=["test"], admin_api_key="secret"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/admin/health", headers={"X-Admin-Key": "secret"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
