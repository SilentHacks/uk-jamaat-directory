from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    CandidateStatus,
    Confidence,
    CorrectionStatus,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.ingest.sources.mylocalmasjid.schema import MyLocalMasjidScheduleRow
from uk_jamaat_directory.models.core import (
    Correction,
    Mosque,
    MosqueClaim,
    MosqueSource,
    ScheduleCandidate,
)
from uk_jamaat_directory.schedules.parse import parse_hhmm
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
) -> tuple[uuid.UUID, int]:
    await _require_mosque(session, mosque_id)
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

    created = 0
    for row in payload.schedules:
        parsed = MyLocalMasjidScheduleRow.model_validate(
            {
                "date": row.date,
                "prayer": row.prayer,
                "start_time": row.start_time,
                "jamaat_time": row.jamaat_time,
                "session_number": row.session_number,
                "session_label": row.session_label,
                "timezone": payload.timezone,
            }
        )
        jamaat_time = parse_hhmm(parsed.jamaat_time)
        if jamaat_time is None:
            continue
        start_time = parse_hhmm(parsed.start_time)
        candidate = ScheduleCandidate(
            id=uuid.uuid4(),
            mosque_id=mosque_id,
            source_id=source.id,
            date=parsed.date,
            prayer=parsed.prayer,
            start_time=start_time,
            jamaat_time=jamaat_time,
            session_number=parsed.session_number,
            session_label=parsed.session_label,
            timezone=parsed.timezone,
            confidence=Confidence.COMMUNITY,
            status=CandidateStatus.PENDING,
            evidence={
                "source_type": SourceType.COMMUNITY.value,
                "submission_id": str(submission_id),
            },
        )
        session.add(candidate)
        created += 1

    await session.flush()
    return submission_id, created


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
