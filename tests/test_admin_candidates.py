from __future__ import annotations

import uuid
from datetime import date, time

import pytest
from fixtures import seed_public_mosque_bundle
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    CandidateStatus,
    Prayer,
)
from uk_jamaat_directory.models.core import ScheduleCandidate

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}


@pytest.mark.asyncio
async def test_admin_list_and_approve_candidate(
    admin_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    bundle = await seed_public_mosque_bundle(db_session)
    source = bundle["public_source"]
    mosque = bundle["mosque"]

    candidate = ScheduleCandidate(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_id=source.id,
        date=date(2026, 6, 7),
        prayer=Prayer.DHUHR,
        start_time=time(13, 0),
        jamaat_time=time(13, 15),
        timezone="Europe/London",
        status=CandidateStatus.PENDING,
    )
    db_session.add(candidate)
    await db_session.commit()

    list_response = await admin_client_with_db.get(
        "/v1/admin/candidates",
        headers=ADMIN_HEADERS,
        params={"status": "pending", "mosque_id": str(mosque.id)},
    )
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["count"] >= 1
    assert payload["items"][0]["candidate_id"] == str(candidate.id)

    approve_response = await admin_client_with_db.post(
        f"/v1/admin/candidates/{candidate.id}/approve",
        headers=ADMIN_HEADERS,
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_admin_reject_candidate(
    admin_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    bundle = await seed_public_mosque_bundle(db_session)
    candidate = ScheduleCandidate(
        id=uuid.uuid4(),
        mosque_id=bundle["mosque"].id,
        source_id=bundle["public_source"].id,
        date=date(2026, 6, 7),
        prayer=Prayer.ASR,
        jamaat_time=time(16, 30),
        timezone="Europe/London",
        status=CandidateStatus.PENDING,
    )
    db_session.add(candidate)
    await db_session.commit()

    response = await admin_client_with_db.post(
        f"/v1/admin/candidates/{candidate.id}/reject",
        headers=ADMIN_HEADERS,
        json={"reason": "duplicate row"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_admin_approve_rejects_unknown_policy_source(
    admin_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    bundle = await seed_public_mosque_bundle(db_session)
    candidate = ScheduleCandidate(
        id=uuid.uuid4(),
        mosque_id=bundle["mosque"].id,
        source_id=bundle["private_source"].id,
        date=date(2026, 6, 7),
        prayer=Prayer.MAGHRIB,
        jamaat_time=time(21, 0),
        timezone="Europe/London",
        status=CandidateStatus.PENDING,
    )
    db_session.add(candidate)
    await db_session.commit()

    response = await admin_client_with_db.post(
        f"/v1/admin/candidates/{candidate.id}/approve",
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_admin_list_candidates_rejects_invalid_status(
    admin_client_with_db: AsyncClient,
) -> None:
    response = await admin_client_with_db.get(
        "/v1/admin/candidates",
        headers=ADMIN_HEADERS,
        params={"status": "not-a-status"},
    )
    assert response.status_code == 422
