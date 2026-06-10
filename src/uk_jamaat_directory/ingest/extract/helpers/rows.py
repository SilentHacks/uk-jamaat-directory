"""Row-level helpers for tabular timetable extraction.

PDF (and some HTML) timetables leave cells blank when a time repeats from
the previous day, and frequently print 12-hour times without am/pm markers.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import time

from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time, infer_ampm


def carry_forward(values: Iterable[str]) -> list[str]:
    """Replace blank cells with the most recent non-blank value."""
    filled: list[str] = []
    last = ""
    for value in values:
        cleaned = (value or "").strip()
        if cleaned in {'"', "''", "“", "”", "-"}:
            cleaned = ""
        if cleaned:
            last = cleaned
        filled.append(last)
    return filled


def coerce_column(values: Sequence[str], *, prayer: str) -> list[time | None]:
    """Parse a column of time strings with prayer-aware am/pm inference."""
    return [coerce_time(value, prayer=prayer) if value else None for value in values]


def coerce_times(values: Sequence[time | None], *, prayer: str) -> list[time | None]:
    """Apply prayer-aware am/pm inference to already-parsed times."""
    return [infer_ampm(value, prayer=prayer) if value else None for value in values]
