from __future__ import annotations

import re
from datetime import time

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
