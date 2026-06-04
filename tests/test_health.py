from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.main import create_app


@pytest.mark.asyncio
async def test_health_endpoint_returns_service_metadata() -> None:
    app = create_app(Settings(allowed_hosts=["test"]))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/health", headers={"X-Request-ID": "test-request"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request"
    assert response.json() == {
        "name": "UK Jamaat Directory",
        "version": "0.1.0",
        "environment": "development",
        "status": "ok",
    }


@pytest.mark.asyncio
async def test_not_found_uses_stable_error_envelope() -> None:
    app = create_app(Settings(allowed_hosts=["test"]))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/missing", headers={"X-Request-ID": "missing-request"})

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Not Found",
            "request_id": "missing-request",
        }
    }
