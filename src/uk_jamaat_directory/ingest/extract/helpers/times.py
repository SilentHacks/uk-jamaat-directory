from __future__ import annotations

import re
from datetime import time

_PATTERN = re.compile(
    r"^\s*(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>(am|pm))?\s*$",
    re.IGNORECASE,
)


def parse_time_loose(value: str) -> time | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    match = _PATTERN.match(cleaned)
    if match is None:
        return None
    hour = int(match.group("h"))
    minute = int(match.group("m") or 0)
    ampm = match.group("ampm")
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return time(hour=hour, minute=minute)


def infer_ampm(value: time, *, prayer: str | None = None) -> time:
    if value.hour < 12:
        return value
    return value


def coerce_time(value: str, *, prayer: str | None = None) -> time | None:
    parsed = parse_time_loose(value)
    if parsed is None:
        return None
    return infer_ampm(parsed, prayer=prayer)
