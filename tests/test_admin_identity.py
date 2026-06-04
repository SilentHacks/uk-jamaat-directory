from __future__ import annotations

import uuid
from datetime import date, time

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    Confidence,
    MosqueStatus,
    Prayer,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.models.core import (
    ModerationAction,
    Mosque,
    MosqueAlias,
    MosqueSource,
    ScheduleCandidate,
)

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
    db_session.add(
        MosqueAlias(
            id=uuid.uuid4(),
            mosque_id=duplicate.id,
            alias="Old Name",
            normalized_alias="old name",
            source_type=SourceType.MANUAL,
        )
    )
    source_for_candidate = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=duplicate.id,
        source_type=SourceType.MANUAL,
        external_id="dup-candidate-source",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.COMMUNITY,
    )
    db_session.add(source_for_candidate)
    db_session.add(
        ScheduleCandidate(
            id=uuid.uuid4(),
            mosque_id=duplicate.id,
            source_id=source_for_candidate.id,
            date=date(2026, 6, 4),
            prayer=Prayer.DHUHR,
            jamaat_time=time(13, 15),
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

    moved_alias = await db_session.scalar(
        select(MosqueAlias).where(MosqueAlias.alias == "Old Name")
    )
    assert moved_alias is not None
    assert str(moved_alias.mosque_id) == canonical_id

    moved_candidate = await db_session.scalar(
        select(ScheduleCandidate).where(ScheduleCandidate.mosque_id == canonical_id)
    )
    assert moved_candidate is not None

    canonical_alias = await db_session.scalar(
        select(MosqueAlias).where(
            MosqueAlias.mosque_id == uuid.UUID(canonical_id),
            MosqueAlias.normalized_alias == "duplicate masjid",
        )
    )
    assert canonical_alias is not None

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
