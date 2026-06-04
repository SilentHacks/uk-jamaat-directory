from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from uk_jamaat_directory.main import app


@pytest.mark.asyncio
async def test_health_endpoint_returns_service_metadata() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "name": "UK Jamaat Directory",
        "version": "0.1.0",
        "environment": "development",
        "status": "ok",
    }
