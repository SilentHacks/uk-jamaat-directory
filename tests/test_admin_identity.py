from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import Confidence, MosqueStatus, SourcePublicationPolicy, SourceType
from uk_jamaat_directory.models.core import ModerationAction, Mosque, MosqueSource

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}


@pytest.mark.asyncio
async def test_admin_create_and_merge_mosque(
    admin_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    create_response = await admin_client_with_db.post(
        "/v1/admin/mosques",
        headers=ADMIN_HEADERS,
        json={
            "name": "Admin Created Masjid",
            "city": "Leeds",
            "postcode": "LS1 1AA",
            "status": "active",
        },
    )
    assert create_response.status_code == 201
    canonical_id = create_response.json()["directory_mosque_id"]

    duplicate = Mosque(
        id=uuid.uuid4(),
        name="Duplicate Masjid",
        normalized_name="duplicate masjid",
        status=MosqueStatus.NEEDS_REVIEW,
    )
    db_session.add(duplicate)
    db_session.add(
        MosqueSource(
            id=uuid.uuid4(),
            mosque_id=duplicate.id,
            source_type=SourceType.MANUAL,
            external_id="dup-1",
            publication_policy=SourcePublicationPolicy.UNKNOWN,
            confidence=Confidence.COMMUNITY,
        )
    )
    await db_session.commit()

    merge_response = await admin_client_with_db.post(
        f"/v1/admin/mosques/{canonical_id}/merge",
        headers=ADMIN_HEADERS,
        json={"duplicate_mosque_id": str(duplicate.id), "reason": "same site"},
    )
    assert merge_response.status_code == 200

    moved_source = await db_session.scalar(
        select(MosqueSource).where(MosqueSource.external_id == "dup-1")
    )
    assert moved_source is not None
    assert str(moved_source.mosque_id) == canonical_id

    actions = (await db_session.scalars(select(ModerationAction))).all()
    assert any(item.action == "merge_mosque" for item in actions)


@pytest.mark.asyncio
async def test_admin_discovery_lead_is_private_metadata(
    admin_client_with_db: AsyncClient,
) -> None:
    response = await admin_client_with_db.post(
        "/v1/admin/discovery-leads",
        headers=ADMIN_HEADERS,
        json={"query": "masjid near E2", "notes": "check manually"},
    )
    assert response.status_code == 200
    assert "Google-derived" in response.json()["message"]
