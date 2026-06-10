"""Semantic plausibility checks for extractor output.

Static AST checks prove a script is *safe*; these checks prove its output
*looks like a real jamaat timetable*: plausible per-prayer time windows,
intra-day ordering, near-future date coverage, and smells that indicate
calculated/aggregator times or hardcoded years.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import ExtractorResult

#: ``no_schedule_reason`` values that legitimately carry zero rows.
ALLOWED_EMPTY_REASONS: tuple[str, ...] = (
    "jumuah_only",
    "awaiting ocr",
    "awaiting OCR",
)

_DAILY_ORDER = (Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA)


def _empty_reason_allowed(reason: str | None) -> bool:
    if not reason:
        return False
    lowered = reason.lower()
    return any(allowed.lower() in lowered for allowed in ALLOWED_EMPTY_REASONS)


def check_result_semantics(result: ExtractorResult, *, today: date | None = None) -> list[str]:
    """Return a list of semantic issues (empty list == plausible)."""
    today = today or date.today()
    issues: list[str] = []

    if not result.rows:
        if not _empty_reason_allowed(result.no_schedule_reason):
            issues.append(
                "extractor produced no rows "
                f"(no_schedule_reason={result.no_schedule_reason!r} is not an "
                "accepted empty-result reason)"
            )
        return issues

    # Per-prayer plausible windows.
    out_of_window = 0
    for row in result.rows:
        window = PLAUSIBLE_WINDOWS.get(row.prayer.value)
        if window and not (window[0] <= row.jamaat_time <= window[1]):
            out_of_window += 1
    if out_of_window:
        issues.append(
            f"{out_of_window}/{len(result.rows)} rows have jamaat times outside "
            "the plausible window for their prayer"
        )

    # Intra-day ordering.
    by_date: dict[date, dict[Prayer, list]] = defaultdict(dict)
    for row in result.rows:
        by_date[row.date].setdefault(row.prayer, []).append(row.jamaat_time)
    disordered_days = 0
    for prayers in by_date.values():
        sequence = [min(prayers[p]) for p in _DAILY_ORDER if p in prayers]
        if len(sequence) >= 2 and sequence != sorted(sequence):
            disordered_days += 1
    if disordered_days:
        issues.append(f"{disordered_days} day(s) have prayers out of chronological order")

    # Date coverage: must include today or the near future.
    dates = {row.date for row in result.rows}
    if not any(today - timedelta(days=1) <= d <= today + timedelta(days=31) for d in dates):
        issues.append(
            f"no rows dated within [today-1, today+31] (dates span {min(dates)}..{max(dates)})"
        )

    # Hardcoded-year smell.
    if all(d.year != today.year for d in dates):
        issues.append(f"all rows are in year(s) other than {today.year} (hardcoded year?)")

    # Calculated-times smell: start_time == jamaat_time everywhere AND the same
    # (prayer, time) pairs repeat across many dates.
    distinct_dates = len(dates)
    if distinct_dates >= 7:
        starts_equal = all(
            row.start_time is not None and row.start_time == row.jamaat_time
            for row in result.rows
        )
        if starts_equal:
            pair_counts = Counter((row.prayer.value, row.jamaat_time) for row in result.rows)
            repeated = sum(c for c in pair_counts.values() if c >= distinct_dates * 0.5)
            if repeated > len(result.rows) * 0.5:
                issues.append(
                    "times look calculated (start==jamaat everywhere and identical "
                    "times repeat across most dates)"
                )

    return issues
