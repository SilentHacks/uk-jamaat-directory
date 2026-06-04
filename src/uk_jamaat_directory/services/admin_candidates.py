from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import CandidateStatus
from uk_jamaat_directory.models.core import ScheduleCandidate
from uk_jamaat_directory.schemas.admin import AdminCandidateSummary
from uk_jamaat_directory.services import schedule_moderation


def candidate_to_summary(candidate: ScheduleCandidate) -> AdminCandidateSummary:
    return AdminCandidateSummary(
        candidate_id=candidate.id,
        directory_mosque_id=candidate.mosque_id,
        source_id=candidate.source_id,
        date=candidate.date,
        prayer=candidate.prayer.value
        if hasattr(candidate.prayer, "value")
        else str(candidate.prayer),
        start_time=candidate.start_time,
        jamaat_time=candidate.jamaat_time,
        session_number=candidate.session_number,
        session_label=candidate.session_label,
        timezone=candidate.timezone,
        confidence=candidate.confidence.value
        if hasattr(candidate.confidence, "value")
        else str(candidate.confidence),
        status=candidate.status.value
        if hasattr(candidate.status, "value")
        else str(candidate.status),
        validation_errors=list(candidate.validation_errors or []),
    )


async def list_candidates(
    session: AsyncSession,
    *,
    status: CandidateStatus | None = None,
    source_id: uuid.UUID | None = None,
    mosque_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
):
    return await schedule_moderation.list_candidates(
        session,
        status=status,
        source_id=source_id,
        mosque_id=mosque_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


async def approve_candidate(
    session: AsyncSession, candidate_id: uuid.UUID, *, actor: str
) -> ScheduleCandidate:
    return await schedule_moderation.approve_candidate(session, candidate_id, actor=actor)


async def reject_candidate(
    session: AsyncSession,
    candidate_id: uuid.UUID,
    *,
    actor: str,
    reason: str | None = None,
) -> ScheduleCandidate:
    return await schedule_moderation.reject_candidate(
        session,
        candidate_id,
        actor=actor,
        reason=reason,
    )
