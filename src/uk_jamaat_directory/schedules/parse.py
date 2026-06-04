from __future__ import annotations

import re
from datetime import date, time

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.schedules.prayers import PRAYER_ALIASES
from uk_jamaat_directory.schedules.types import ScheduleCandidateInput

_TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_hhmm(value: str | None) -> time | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    match = _TIME_PATTERN.match(stripped)
    if match is None:
        msg = f"invalid time format (expected HH:MM): {value}"
        raise ValueError(msg)
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        msg = f"invalid time value: {value}"
        raise ValueError(msg)
    return time(hour=hour, minute=minute)


def parse_prayer(value: str) -> Prayer:
    key = value.strip().lower()
    if key not in PRAYER_ALIASES:
        msg = f"unsupported prayer: {value}"
        raise ValueError(msg)
    return PRAYER_ALIASES[key]


def parse_schedule_row(
    *,
    on_date: date,
    prayer: str,
    jamaat_time: str,
    start_time: str | None = None,
    session_number: int = 1,
    session_label: str | None = None,
    timezone: str = "Europe/London",
) -> tuple[ScheduleCandidateInput, time, time | None]:
    parsed_jamaat = parse_hhmm(jamaat_time)
    if parsed_jamaat is None:
        msg = f"invalid jamaat time (expected HH:MM): {jamaat_time}"
        raise ValueError(msg)
    row = ScheduleCandidateInput(
        date=on_date,
        prayer=parse_prayer(prayer),
        session_number=session_number,
        session_label=session_label,
        timezone=timezone,
    )
    return row, parsed_jamaat, parse_hhmm(start_time)
