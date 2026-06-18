from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import SourceType
from uk_jamaat_directory.models.core import Correction, MosqueClaim, MosqueSource, ScheduleCandidate
from uk_jamaat_directory.schemas.public import MosqueDetailPublic, TimesResponse


@pytest.mark.asyncio
async def test_community_submission_stores_private_contact(
    client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    response = await client_with_db.post(
        "/v1/contributions/mosques",
        json={
            "name": "Community Submitted Masjid",
            "city": "Birmingham",
            "postcode": "B1 1AA",
            "submitter_name": "Private Person",
            "submitter_email": "private@example.org",
            "message": "Missing from map",
        },
    )
    assert response.status_code == 202
    submission_id = response.json()["submission_id"]

    source = await db_session.scalar(
        select(MosqueSource).where(
            MosqueSource.source_type == SourceType.COMMUNITY,
            MosqueSource.external_id == submission_id,
        )
    )
    assert source is not None
    assert source.metadata_["submitter_email"] == "private@example.org"
    assert source.publication_policy.value == "unknown"

    public_fields = set(MosqueDetailPublic.model_fields)
    assert "submitter_email" not in public_fields


@pytest.mark.asyncio
async def test_mosque_correction_submission(
    client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    from fixtures import seed_public_mosque_bundle

    bundle = await seed_public_mosque_bundle(db_session)
    mosque_id = bundle["mosque"].id

    response = await client_with_db.post(
        f"/v1/mosques/{mosque_id}/corrections",
        json={
            "message": "Dhuhr jamaat looks wrong",
            "occurrence_id": str(bundle["public_occurrence"].id),
            "submitter_name": "Private Person",
            "submitter_email": "private@example.org",
            "suggested": {"jamaat_time": "13:20"},
        },
    )
    assert response.status_code == 202
    correction_id = response.json()["submission_id"]

    correction = await db_session.get(Correction, correction_id)
    assert correction is not None
    assert correction.submitter_email == "private@example.org"
    assert correction.status.value == "pending"

    public_fields = set(TimesResponse.model_fields)
    assert "submitter_email" not in public_fields


@pytest.mark.asyncio
async def test_mosque_schedule_submission_creates_pending_candidates(
    client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    from fixtures import seed_public_mosque_bundle

    bundle = await seed_public_mosque_bundle(db_session)
    mosque_id = bundle["mosque"].id

    response = await client_with_db.post(
        f"/v1/mosques/{mosque_id}/schedule-submissions",
        json={
            "timezone": "Europe/London",
            "schedules": [
                {
                    "date": "2026-06-08",
                    "prayer": "fajr",
                    "start_time": "04:00",
                    "jamaat_time": "04:15",
                }
            ],
            "submitter_email": "private@example.org",
        },
    )
    assert response.status_code == 202

    pending = await db_session.scalar(
        select(ScheduleCandidate).where(ScheduleCandidate.mosque_id == mosque_id)
    )
    assert pending is not None
    assert pending.status.value == "pending"
    payload = response.json()
    assert payload["rows_accepted"] == 1
    assert payload["rows_rejected"] == 0


@pytest.mark.asyncio
async def test_community_schedule_stays_pending_after_validate(
    db_session: AsyncSession,
) -> None:
    from datetime import date

    from fixtures import seed_public_mosque_bundle

    from uk_jamaat_directory.domain import SourceType
    from uk_jamaat_directory.models.core import MosqueSource, ScheduleCandidate
    from uk_jamaat_directory.schedules.publication import validate_candidates
    from uk_jamaat_directory.schemas.contributions import (
        MosqueScheduleSubmission,
        ScheduleSubmissionRow,
    )
    from uk_jamaat_directory.services.contribution_intake import submit_schedule

    bundle = await seed_public_mosque_bundle(db_session)
    mosque_id = bundle["mosque"].id
    _submission_id, accepted, _rejected = await submit_schedule(
        db_session,
        mosque_id,
        MosqueScheduleSubmission(
            schedules=[
                    ScheduleSubmissionRow(
                        date=date.today(),
                        prayer="fajr",
                        jamaat_time="04:15",
                    )
            ]
        ),
    )
    assert accepted == 1
    await db_session.commit()

    candidate = await db_session.scalar(
        select(ScheduleCandidate)
        .join(MosqueSource, ScheduleCandidate.source_id == MosqueSource.id)
        .where(ScheduleCandidate.mosque_id == mosque_id)
        .where(MosqueSource.source_type == SourceType.COMMUNITY)
    )
    assert candidate is not None

    await validate_candidates(db_session)
    await db_session.refresh(candidate)
    assert candidate.status.value == "pending"


@pytest.mark.asyncio
async def test_mosque_claim_submission(
    client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    from fixtures import seed_public_mosque_bundle

    bundle = await seed_public_mosque_bundle(db_session)
    mosque_id = bundle["mosque"].id

    response = await client_with_db.post(
        f"/v1/mosques/{mosque_id}/claims",
        json={
            "claimant_name": "Trustee",
            "claimant_email": "trustee@example.org",
            "claimant_role": "chair",
        },
    )
    assert response.status_code == 202
    claim_id = response.json()["submission_id"]

    claim = await db_session.get(MosqueClaim, claim_id)
    assert claim is not None
    assert claim.claimant_email == "trustee@example.org"
    assert claim.status.value == "pending"
