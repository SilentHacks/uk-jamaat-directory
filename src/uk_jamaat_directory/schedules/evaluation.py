from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.domain import CandidateStatus
from uk_jamaat_directory.models.core import ScheduleCandidate
from uk_jamaat_directory.schedules.gates import can_publish_candidate
from uk_jamaat_directory.schedules.prefetch import ValidationBatchContext
from uk_jamaat_directory.schedules.types import ValidationResult
from uk_jamaat_directory.schedules.validation import status_after_validation, validate_candidate

EvaluationMode = Literal["validate", "approve", "publish"]


@dataclass(frozen=True)
class CandidateEvaluation:
    validation: ValidationResult
    policy_allowed: bool
    policy_reason: str | None
    status: CandidateStatus


def evaluate_candidate_in_context(
    candidate: ScheduleCandidate,
    context: ValidationBatchContext,
    *,
    mode: EvaluationMode,
    settings: Settings | None = None,
) -> CandidateEvaluation:
    cfg = settings or get_settings()
    source = context.sources.get(candidate.source_id)
    if source is None:
        empty = ValidationResult()
        return CandidateEvaluation(
            validation=empty,
            policy_allowed=False,
            policy_reason="candidate source not found",
            status=CandidateStatus.REJECTED,
        )

    mosque = context.mosques.get(candidate.mosque_id) if candidate.mosque_id is not None else None
    extraction_kind = context.extraction_kinds.get(candidate.id)
    validation = validate_candidate(
        candidate,
        mosque=mosque,
        source=source,
        duplicate_ids=context.duplicate_ids.get(candidate.id),
        extraction_kind=extraction_kind,
        settings=cfg,
    )

    policy_allowed = True
    policy_reason: str | None = None
    if mode in ("approve", "publish"):
        policy_allowed, policy_reason = can_publish_candidate(
            source,
            extraction_kind=extraction_kind,
            settings=cfg,
        )

    status = status_after_validation(
        validation,
        extraction_kind=extraction_kind,
        source=source,
        candidate=candidate,
        settings=cfg,
    )
    return CandidateEvaluation(
        validation=validation,
        policy_allowed=policy_allowed,
        policy_reason=policy_reason,
        status=status,
    )


def apply_validation_result(
    candidate: ScheduleCandidate,
    evaluation: CandidateEvaluation,
    *,
    update_status: bool,
) -> None:
    candidate.validation_errors = evaluation.validation.to_error_list()
    if update_status:
        candidate.status = evaluation.status
