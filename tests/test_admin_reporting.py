from __future__ import annotations

import pytest
from fixtures import seed_public_mosque_bundle
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.models.core import SourceHealth

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}


@pytest.mark.asyncio
async def test_admin_coverage_and_source_health(
    admin_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    bundle = await seed_public_mosque_bundle(db_session)
    db_session.add(
        SourceHealth(
            source_id=bundle["public_source"].id,
            freshness_status="fresh",
            next_7_days_coverage=7,
            message="ok",
        )
    )
    await db_session.commit()

    coverage_response = await admin_client_with_db.get(
        "/v1/admin/coverage",
        headers=ADMIN_HEADERS,
    )
    assert coverage_response.status_code == 200
    coverage = coverage_response.json()
    assert coverage["mosque_count"] >= 1
    assert coverage["source_count"] >= 2
    assert "public_redistribution_allowed" in coverage["policy_counts"]

    health_response = await admin_client_with_db.get(
        "/v1/admin/source-health",
        headers=ADMIN_HEADERS,
        params={"mosque_id": str(bundle["mosque"].id)},
    )
    assert health_response.status_code == 200
    health_payload = health_response.json()
    assert health_payload["count"] >= 1
    assert health_payload["items"][0]["freshness_status"] == "fresh"
