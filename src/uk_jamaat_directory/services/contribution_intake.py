from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    Confidence,
    CorrectionStatus,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.models.core import (
    Correction,
    Mosque,
    MosqueClaim,
    MosqueSource,
)
from uk_jamaat_directory.schedules.candidates import upsert_schedule_candidate
from uk_jamaat_directory.schedules.parse import parse_schedule_row
from uk_jamaat_directory.schemas.contributions import (
    MosqueClaimSubmission,
    MosqueCorrectionSubmission,
    MosqueScheduleSubmission,
)
from uk_jamaat_directory.services.errors import MosqueNotFoundError


async def _require_mosque(session: AsyncSession, mosque_id: uuid.UUID) -> Mosque:
    mosque = await session.get(Mosque, mosque_id)
    if mosque is None:
        raise MosqueNotFoundError(str(mosque_id))
    return mosque


async def submit_correction(
    session: AsyncSession,
    mosque_id: uuid.UUID,
    payload: MosqueCorrectionSubmission,
) -> uuid.UUID:
    await _require_mosque(session, mosque_id)
    correction = Correction(
        id=uuid.uuid4(),
        mosque_id=mosque_id,
        occurrence_id=payload.occurrence_id,
        submitter_name=payload.submitter_name,
        submitter_email=payload.submitter_email,
        message=payload.message,
        status=CorrectionStatus.PENDING,
        payload={
            "suggested": payload.suggested,
            "private_contact": True,
        },
    )
    session.add(correction)
    await session.flush()
    return correction.id


async def submit_schedule(
    session: AsyncSession,
    mosque_id: uuid.UUID,
    payload: MosqueScheduleSubmission,
) -> tuple[uuid.UUID, int, int]:
    mosque = await _require_mosque(session, mosque_id)
    submission_id = uuid.uuid4()
    source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque_id,
        source_type=SourceType.COMMUNITY,
        external_id=f"schedule-{submission_id}",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.COMMUNITY,
        last_seen_at=datetime.now(UTC),
        metadata_={
            "message": payload.message,
            "submitter_name": payload.submitter_name,
            "submitter_email": payload.submitter_email,
            "private_contact": True,
            "submission_kind": "schedule",
        },
    )
    session.add(source)
    await session.flush()

    accepted = 0
    rejected = 0
    evidence_extra = {
        "source_type": SourceType.COMMUNITY.value,
        "submission_id": str(submission_id),
    }
    for row in payload.schedules:
        try:
            candidate_input, jamaat_time, start_time = parse_schedule_row(
                on_date=row.date,
                prayer=row.prayer,
                start_time=row.start_time,
                jamaat_time=row.jamaat_time,
                session_number=row.session_number,
                session_label=row.session_label,
                timezone=payload.timezone,
            )
        except ValueError:
            rejected += 1
            continue

        await upsert_schedule_candidate(
            session,
            mosque=mosque,
            source=source,
            extraction_run_id=None,
            row=candidate_input,
            jamaat_time=jamaat_time,
            start_time=start_time,
            evidence_extra=evidence_extra,
        )
        accepted += 1

    await session.flush()
    return submission_id, accepted, rejected


async def submit_claim(
    session: AsyncSession,
    mosque_id: uuid.UUID,
    payload: MosqueClaimSubmission,
) -> uuid.UUID:
    await _require_mosque(session, mosque_id)
    claim = MosqueClaim(
        id=uuid.uuid4(),
        mosque_id=mosque_id,
        claimant_name=payload.claimant_name,
        claimant_email=payload.claimant_email,
        claimant_role=payload.claimant_role,
        verification_evidence={
            **payload.verification_evidence,
            "private_contact": True,
        },
    )
    session.add(claim)
    await session.flush()
    return claim.id
