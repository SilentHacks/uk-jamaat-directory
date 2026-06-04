from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import CandidateStatus
from uk_jamaat_directory.models.core import (
    ModerationAction,
    Mosque,
    MosqueSource,
    ScheduleCandidate,
)
from uk_jamaat_directory.schedules.validation import (
    find_duplicate_candidate_ids,
    resolve_extraction_kind,
    validate_candidate,
)


@dataclass
class CandidateListResult:
    items: list[ScheduleCandidate]
    total: int
    limit: int
    offset: int


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
) -> CandidateListResult:
    filters = []
    if status is not None:
        filters.append(ScheduleCandidate.status == status)
    if source_id is not None:
        filters.append(ScheduleCandidate.source_id == source_id)
    if mosque_id is not None:
        filters.append(ScheduleCandidate.mosque_id == mosque_id)
    if date_from is not None:
        filters.append(ScheduleCandidate.date >= date_from)
    if date_to is not None:
        filters.append(ScheduleCandidate.date <= date_to)

    count_stmt = select(func.count()).select_from(ScheduleCandidate)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = select(ScheduleCandidate).order_by(ScheduleCandidate.date.desc())
    if filters:
        stmt = stmt.where(*filters)
    stmt = stmt.offset(offset).limit(limit)
    items = (await session.execute(stmt)).scalars().all()

    return CandidateListResult(items=list(items), total=total, limit=limit, offset=offset)


async def _audit(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    candidate_id: uuid.UUID,
    reason: str | None = None,
) -> None:
    session.add(
        ModerationAction(
            actor=actor,
            action=action,
            entity_type="schedule_candidate",
            entity_id=candidate_id,
            reason=reason,
        )
    )


async def approve_candidate(
    session: AsyncSession,
    candidate_id: uuid.UUID,
    *,
    actor: str,
) -> ScheduleCandidate:
    candidate = await session.get(ScheduleCandidate, candidate_id)
    if candidate is None:
        msg = f"candidate not found: {candidate_id}"
        raise ValueError(msg)

    source = await session.get(MosqueSource, candidate.source_id)
    mosque = (
        await session.get(Mosque, candidate.mosque_id) if candidate.mosque_id else None
    )
    if source is None:
        msg = "candidate source not found"
        raise ValueError(msg)

    dupes = await find_duplicate_candidate_ids(session, candidate)
    extraction_kind = await resolve_extraction_kind(session, candidate)
    validation = validate_candidate(
        candidate,
        mosque=mosque,
        source=source,
        duplicate_ids=dupes,
        extraction_kind=extraction_kind,
    )
    candidate.validation_errors = validation.to_error_list()
    if not validation.is_valid:
        msg = "candidate has validation errors and cannot be approved"
        raise ValueError(msg)

    candidate.status = CandidateStatus.APPROVED
    await _audit(session, actor=actor, action="approve_candidate", candidate_id=candidate_id)
    await session.flush()
    return candidate


async def reject_candidate(
    session: AsyncSession,
    candidate_id: uuid.UUID,
    *,
    actor: str,
    reason: str | None = None,
) -> ScheduleCandidate:
    candidate = await session.get(ScheduleCandidate, candidate_id)
    if candidate is None:
        msg = f"candidate not found: {candidate_id}"
        raise ValueError(msg)

    candidate.status = CandidateStatus.REJECTED
    await _audit(
        session,
        actor=actor,
        action="reject_candidate",
        candidate_id=candidate_id,
        reason=reason,
    )
    await session.flush()
    return candidate
