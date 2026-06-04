from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.domain import CandidateStatus
from uk_jamaat_directory.models.core import ScheduleCandidate
from uk_jamaat_directory.schedules.evaluation import (
    apply_validation_result,
    evaluate_candidate_in_context,
)
from uk_jamaat_directory.schedules.prefetch import build_validation_batch_context


async def approve_candidate_status(
    session: AsyncSession,
    candidate: ScheduleCandidate,
    *,
    settings: Settings | None = None,
) -> ScheduleCandidate:
    cfg = settings or get_settings()
    context = await build_validation_batch_context(session, [candidate])
    evaluation = evaluate_candidate_in_context(
        candidate,
        context,
        mode="approve",
        settings=cfg,
    )
    if not evaluation.policy_allowed:
        raise ValueError(
            evaluation.policy_reason or "candidate cannot be published under source policy"
        )
    if not evaluation.validation.is_valid:
        msg = "candidate has validation errors and cannot be approved"
        raise ValueError(msg)
    if evaluation.status != CandidateStatus.APPROVED:
        msg = "candidate requires manual review before approval"
        raise ValueError(msg)

    apply_validation_result(candidate, evaluation, update_status=True)
    await session.flush()
    return candidate
