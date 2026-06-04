from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.domain import CandidateStatus, ExtractionKind, Prayer
from uk_jamaat_directory.models.core import ExtractionRun, Mosque, MosqueSource, ScheduleCandidate
from uk_jamaat_directory.schedules.types import IssueSeverity, ValidationIssue, ValidationResult

ACTIVE_CANDIDATE_STATUSES = (
    CandidateStatus.PENDING,
    CandidateStatus.APPROVED,
)

DAILY_PRAYERS = (
    Prayer.FAJR,
    Prayer.DHUHR,
    Prayer.ASR,
    Prayer.MAGHRIB,
    Prayer.ISHA,
)


def _today_in_timezone(timezone_name: str) -> date:
    return datetime.now(ZoneInfo(timezone_name)).date()


def validate_candidate(
    candidate: ScheduleCandidate,
    *,
    mosque: Mosque | None,
    source: MosqueSource,
    duplicate_ids: set[uuid.UUID] | None = None,
    extraction_kind: ExtractionKind | None = None,
    settings: Settings | None = None,
) -> ValidationResult:
    cfg = settings or get_settings()
    result = ValidationResult()
    tz_name = candidate.timezone or "Europe/London"

    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        result.issues.append(
            ValidationIssue(
                code="invalid_timezone",
                severity=IssueSeverity.ERROR,
                field="timezone",
                message=f"unknown timezone: {tz_name}",
            )
        )
        tz = None

    if candidate.mosque_id is None:
        result.issues.append(
            ValidationIssue(
                code="missing_mosque",
                severity=IssueSeverity.ERROR,
                field="mosque_id",
                message="candidate is not linked to a mosque",
            )
        )

    if candidate.jamaat_time is None:
        result.issues.append(
            ValidationIssue(
                code="missing_jamaat",
                severity=IssueSeverity.ERROR,
                field="jamaat_time",
                message="jamaat time is required",
            )
        )

    if candidate.session_number < 1:
        result.issues.append(
            ValidationIssue(
                code="invalid_session_number",
                severity=IssueSeverity.ERROR,
                field="session_number",
                message="session_number must be at least 1",
            )
        )

    if tz is not None:
        today = _today_in_timezone(tz_name)
        earliest = today - timedelta(days=cfg.schedule_date_past_days)
        latest = today + timedelta(days=cfg.schedule_date_future_days)
        if candidate.date < earliest or candidate.date > latest:
            result.issues.append(
                ValidationIssue(
                    code="date_out_of_range",
                    severity=IssueSeverity.ERROR,
                    field="date",
                    message=(
                        f"date {candidate.date} outside allowed window {earliest} to {latest}"
                    ),
                )
            )

        if candidate.prayer == Prayer.JUMUAH:
            weekday = candidate.date.weekday()
            if weekday != 4:
                result.issues.append(
                    ValidationIssue(
                        code="jumuah_not_friday",
                        severity=IssueSeverity.ERROR,
                        field="date",
                        message=f"jumuah must fall on Friday in {tz_name}, got weekday {weekday}",
                    )
                )

        if candidate.start_time and candidate.jamaat_time:
            if candidate.jamaat_time < candidate.start_time:
                result.issues.append(
                    ValidationIssue(
                        code="jamaat_before_start",
                        severity=IssueSeverity.ERROR,
                        field="jamaat_time",
                        message="jamaat time must not be before start time on the same day",
                    )
                )
            start_mins = candidate.start_time.hour * 60 + candidate.start_time.minute
            jamaat_mins = candidate.jamaat_time.hour * 60 + candidate.jamaat_time.minute
            if jamaat_mins - start_mins > 90:
                result.issues.append(
                    ValidationIssue(
                        code="jamaat_far_from_start",
                        severity=IssueSeverity.WARNING,
                        field="jamaat_time",
                        message="jamaat is more than 90 minutes after start time",
                    )
                )

        _append_dst_warnings(result, candidate.date, candidate.jamaat_time, tz, tz_name)
        if candidate.start_time:
            _append_dst_warnings(
                result, candidate.date, candidate.start_time, tz, tz_name, field="start_time"
            )

    if duplicate_ids:
        others = duplicate_ids - {candidate.id}
        if others:
            result.issues.append(
                ValidationIssue(
                    code="duplicate_session",
                    severity=IssueSeverity.ERROR,
                    field="session_number",
                    message=f"duplicate active candidate(s) for same session: {len(others)}",
                )
            )

    evidence = candidate.evidence or {}
    if evidence.get("ramadan_schedule") and evidence.get("ramadan_span_days", 0) > 35:
        result.issues.append(
            ValidationIssue(
                code="ramadan_metadata",
                severity=IssueSeverity.WARNING,
                field="evidence",
                message="Ramadan schedule metadata spans more than 35 days without daily rows",
            )
        )

    if extraction_kind == ExtractionKind.AI and result.is_valid:
        result.issues.append(
            ValidationIssue(
                code="ai_requires_review",
                severity=IssueSeverity.WARNING,
                field="extraction_run",
                message="AI extraction cannot be auto-approved",
            )
        )

    return result


def _append_dst_warnings(
    result: ValidationResult,
    on_date: date,
    at_time: time | None,
    tz: ZoneInfo,
    tz_name: str,
    *,
    field: str = "jamaat_time",
) -> None:
    if at_time is None:
        return
    local_dt = datetime.combine(on_date, at_time, tzinfo=tz)
    try:
        utc = local_dt.astimezone(ZoneInfo("UTC"))
    except (OSError, ValueError):
        result.issues.append(
            ValidationIssue(
                code="dst_gap_hour",
                severity=IssueSeverity.WARNING,
                field=field,
                message=f"time {at_time} is invalid or ambiguous during DST in {tz_name}",
            )
        )
        return

    fold = local_dt.fold
    if fold == 1:
        result.issues.append(
            ValidationIssue(
                code="dst_ambiguous_hour",
                severity=IssueSeverity.WARNING,
                field=field,
                message=f"time {at_time} falls in DST fall-back ambiguous hour in {tz_name}",
            )
        )
    _ = utc


async def find_duplicate_candidate_ids(
    session: AsyncSession,
    candidate: ScheduleCandidate,
) -> set[uuid.UUID]:
    if candidate.mosque_id is None:
        return set()

    stmt = (
        select(ScheduleCandidate.id)
        .where(ScheduleCandidate.mosque_id == candidate.mosque_id)
        .where(ScheduleCandidate.source_id == candidate.source_id)
        .where(ScheduleCandidate.date == candidate.date)
        .where(ScheduleCandidate.prayer == candidate.prayer)
        .where(ScheduleCandidate.session_number == candidate.session_number)
        .where(ScheduleCandidate.status.in_(ACTIVE_CANDIDATE_STATUSES))
        .where(ScheduleCandidate.id != candidate.id)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return set(rows)


async def resolve_extraction_kind(
    session: AsyncSession,
    candidate: ScheduleCandidate,
) -> ExtractionKind | None:
    if candidate.extraction_run_id is None:
        return None
    run = await session.get(ExtractionRun, candidate.extraction_run_id)
    if run is None:
        return None
    return run.kind


def status_after_validation(
    result: ValidationResult,
    *,
    extraction_kind: ExtractionKind | None,
) -> CandidateStatus:
    if not result.is_valid:
        return CandidateStatus.REJECTED
    if extraction_kind == ExtractionKind.AI:
        return CandidateStatus.PENDING
    return CandidateStatus.APPROVED
