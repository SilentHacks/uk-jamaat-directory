from __future__ import annotations

import re
from datetime import time, timedelta


_OFFSET_PATTERN = re.compile(
    r"(?P<minutes>\d{1,3})\s*(?:minute|min|minutes|mins|m)(?:\s|$|[^\w])",
    re.IGNORECASE,
)


def add_minutes(value: time, minutes: int) -> time:
    base = timedelta(hours=value.hour, minutes=value.minute)
    shifted = (base + timedelta(minutes=minutes)) % timedelta(days=1)
    total = int(shifted.total_seconds() // 60)
    return time(hour=total // 60, minute=total % 60)


def jamaat_after_start(start: time, *, minutes: int = 5) -> time:
    return add_minutes(start, minutes)


def parse_offset_minutes(value: str) -> int | None:
    if not value:
        return None
    match = _OFFSET_PATTERN.search(value)
    if match is None:
        return None
    return int(match.group("minutes"))
