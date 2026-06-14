from __future__ import annotations

import uuid
from datetime import date, time, timedelta

from uk_jamaat_directory.domain import (
    CandidateStatus,
    Confidence,
    ExtractionKind,
    MosqueStatus,
    Prayer,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.models.core import Mosque, MosqueSource, ScheduleCandidate
from uk_jamaat_directory.schedules.gates import can_publish_candidate
from uk_jamaat_directory.schedules.validation import (
    status_after_validation,
    validate_candidate,
)


def _mosque() -> Mosque:
    return Mosque(
        id=uuid.uuid4(),
        name="Test Masjid",
        normalized_name="test masjid",
        status=MosqueStatus.ACTIVE,
    )


def _source(*, policy: SourcePublicationPolicy = SourcePublicationPolicy.UNKNOWN) -> MosqueSource:
    return MosqueSource(
        id=uuid.uuid4(),
        mosque_id=uuid.uuid4(),
        source_type=SourceType.MYLOCALMASJID,
        external_id="ext-1",
        publication_policy=policy,
        confidence=Confidence.PARTNER_IMPORT,
    )


def _candidate(
    *,
    on_date: date | None = None,
    prayer: Prayer = Prayer.FAJR,
    start: time | None = time(5, 0),
    jamaat: time | None = time(5, 30),
) -> ScheduleCandidate:
    today = date.today()
    return ScheduleCandidate(
        id=uuid.uuid4(),
        mosque_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        date=on_date or today,
        prayer=prayer,
        start_time=start,
        jamaat_time=jamaat,
        session_number=1,
        timezone="Europe/London",
        confidence=Confidence.PARTNER_IMPORT,
        status=CandidateStatus.PENDING,
    )


def _next_friday() -> date:
    # Use an upcoming Friday so the candidate falls inside the validator's
    # allowed date window (anchored on today) rather than a hardcoded past date.
    today = date.today()
    return today + timedelta(days=(4 - today.weekday()) % 7)


def test_rejects_missing_jamaat() -> None:
    candidate = _candidate(jamaat=None)
    result = validate_candidate(candidate, mosque=_mosque(), source=_source())
    assert any(issue.code == "missing_jamaat" for issue in result.errors)


def test_rejects_jamaat_before_start() -> None:
    candidate = _candidate(start=time(13, 0), jamaat=time(12, 30))
    result = validate_candidate(candidate, mosque=_mosque(), source=_source())
    assert any(issue.code == "jamaat_before_start" for issue in result.errors)


def test_rejects_jumuah_not_friday() -> None:
    saturday = _next_friday() + timedelta(days=1)
    assert saturday.weekday() == 5
    candidate = _candidate(on_date=saturday, prayer=Prayer.JUMUAH, start=None, jamaat=time(13, 0))
    result = validate_candidate(candidate, mosque=_mosque(), source=_source())
    assert any(issue.code == "jumuah_not_friday" for issue in result.errors)


def test_accepts_jumuah_on_friday() -> None:
    friday = _next_friday()
    assert friday.weekday() == 4
    candidate = _candidate(on_date=friday, prayer=Prayer.JUMUAH, start=None, jamaat=time(13, 0))
    result = validate_candidate(candidate, mosque=_mosque(), source=_source())
    assert result.is_valid


def test_warns_jamaat_far_from_start() -> None:
    candidate = _candidate(start=time(5, 0), jamaat=time(7, 0))
    result = validate_candidate(candidate, mosque=_mosque(), source=_source())
    assert result.is_valid
    assert any(issue.code == "jamaat_far_from_start" for issue in result.warnings)


def test_mosque_website_requires_manual_approval() -> None:
    candidate = _candidate()
    source = _source()
    source.source_type = SourceType.MOSQUE_WEBSITE
    result = validate_candidate(candidate, mosque=_mosque(), source=source)
    assert result.is_valid
    assert (
        status_after_validation(
            result,
            extraction_kind=ExtractionKind.DETERMINISTIC,
            source=source,
            candidate=candidate,
        )
        == CandidateStatus.PENDING
    )


def test_mosque_website_with_gate_evidence_auto_approves() -> None:
    from uk_jamaat_directory.config import Settings, get_settings

    candidate = _candidate()
    candidate.evidence = {
        "contract": "repo_site_extractor/v1",
        "gate_passed": True,
        "extractor_key": "synthetic_html_table",
    }
    source = _source()
    source.source_type = SourceType.MOSQUE_WEBSITE
    settings = Settings(
        **{**get_settings().model_dump(), "repo_extractor_auto_approve_candidates": True}
    )
    result = validate_candidate(candidate, mosque=_mosque(), source=source, settings=settings)
    assert result.is_valid
    assert (
        status_after_validation(
            result,
            extraction_kind=ExtractionKind.DETERMINISTIC,
            source=source,
            candidate=candidate,
            settings=settings,
        )
        == CandidateStatus.APPROVED
    )


def test_mosque_website_without_gate_evidence_stays_pending_even_when_auto_enabled() -> None:
    from uk_jamaat_directory.config import Settings, get_settings

    candidate = _candidate()
    source = _source()
    source.source_type = SourceType.MOSQUE_WEBSITE
    settings = Settings(
        **{**get_settings().model_dump(), "repo_extractor_auto_approve_candidates": True}
    )
    result = validate_candidate(candidate, mosque=_mosque(), source=source, settings=settings)
    assert (
        status_after_validation(
            result,
            extraction_kind=ExtractionKind.DETERMINISTIC,
            source=source,
            candidate=candidate,
            settings=settings,
        )
        == CandidateStatus.PENDING
    )


def test_ai_extraction_stays_pending_after_validation() -> None:
    candidate = _candidate()
    result = validate_candidate(
        candidate,
        mosque=_mosque(),
        source=_source(),
        extraction_kind=ExtractionKind.AI,
    )
    assert result.is_valid
    assert (
        status_after_validation(result, extraction_kind=ExtractionKind.AI)
        == CandidateStatus.PENDING
    )


def test_publish_gate_blocks_unknown_policy() -> None:
    allowed, reason = can_publish_candidate(
        _source(policy=SourcePublicationPolicy.UNKNOWN),
        extraction_kind=ExtractionKind.DETERMINISTIC,
    )
    assert not allowed
    assert reason is not None


def test_publish_gate_allows_public_policy() -> None:
    allowed, _ = can_publish_candidate(
        _source(policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED),
        extraction_kind=ExtractionKind.DETERMINISTIC,
    )
    assert allowed


def test_dst_transition_date_in_allowed_window() -> None:
    # UK fall-back Sunday; validator must accept the date within the configured window.
    candidate = _candidate(on_date=date(2026, 10, 25), jamaat=time(1, 30), start=None)
    result = validate_candidate(candidate, mosque=_mosque(), source=_source())
    assert not any(issue.code == "date_out_of_range" for issue in result.errors)


def test_date_out_of_range() -> None:
    far = date.today() + timedelta(days=500)
    candidate = _candidate(on_date=far)
    result = validate_candidate(candidate, mosque=_mosque(), source=_source())
    assert any(issue.code == "date_out_of_range" for issue in result.errors)


def test_invalid_timezone() -> None:
    candidate = _candidate()
    candidate.timezone = "Not/A/Zone"
    result = validate_candidate(candidate, mosque=_mosque(), source=_source())
    assert any(issue.code == "invalid_timezone" for issue in result.errors)
