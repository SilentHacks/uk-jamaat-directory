from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.domain import CandidateStatus
from uk_jamaat_directory.models.core import ScheduleCandidate
from uk_jamaat_directory.schedules.gates import can_publish_candidate
from uk_jamaat_directory.schedules.prefetch import build_validation_batch_context
from uk_jamaat_directory.schedules.validation import status_after_validation, validate_candidate


async def approve_candidate_status(
    session: AsyncSession,
    candidate: ScheduleCandidate,
    *,
    settings: Settings | None = None,
) -> ScheduleCandidate:
    cfg = settings or get_settings()
    context = await build_validation_batch_context(session, [candidate])
    source = context.sources.get(candidate.source_id)
    if source is None:
        msg = "candidate source not found"
        raise ValueError(msg)

    mosque = context.mosques.get(candidate.mosque_id) if candidate.mosque_id else None
    extraction_kind = context.extraction_kinds.get(candidate.id)
    allowed, reason = can_publish_candidate(source, extraction_kind=extraction_kind, settings=cfg)
    if not allowed:
        raise ValueError(reason or "candidate cannot be published under source policy")

    validation = validate_candidate(
        candidate,
        mosque=mosque,
        source=source,
        duplicate_ids=context.duplicate_ids.get(candidate.id),
        extraction_kind=extraction_kind,
        settings=cfg,
    )
    candidate.validation_errors = validation.to_error_list()
    if not validation.is_valid:
        msg = "candidate has validation errors and cannot be approved"
        raise ValueError(msg)

    new_status = status_after_validation(validation, extraction_kind=extraction_kind)
    if new_status != CandidateStatus.APPROVED:
        msg = "candidate requires manual review before approval"
        raise ValueError(msg)

    candidate.status = new_status
    await session.flush()
    return candidate
