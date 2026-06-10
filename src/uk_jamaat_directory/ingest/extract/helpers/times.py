from __future__ import annotations

import re
from datetime import time

_PATTERN = re.compile(
    r"^\s*(?P<h>\d{1,2})(?:[.:](?P<m>\d{2}))?\s*(?P<ampm>(am|pm))?\.?\s*$",
    re.IGNORECASE,
)

# Plausible UK windows per prayer, used to disambiguate 12-hour clock values
# written without an am/pm marker (very common on mosque timetables).
PLAUSIBLE_WINDOWS: dict[str, tuple[time, time]] = {
    "fajr": (time(2, 0), time(7, 30)),
    "dhuhr": (time(11, 30), time(16, 0)),
    "asr": (time(13, 30), time(19, 30)),
    "maghrib": (time(15, 30), time(22, 30)),
    "isha": (time(17, 0), time(23, 59)),
    "jumuah": (time(11, 30), time(15, 30)),
}


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


def _in_window(value: time, window: tuple[time, time]) -> bool:
    return window[0] <= value <= window[1]


def infer_ampm(value: time, *, prayer: str | None = None) -> time:
    """Disambiguate a 12-hour clock value with no am/pm marker.

    If the value falls outside the prayer's plausible window but adding 12
    hours puts it inside, prefer the PM interpretation (e.g. Isha "9:45"
    means 21:45). Values >= 13:00 are already unambiguous.
    """
    if prayer is None or value.hour >= 13:
        return value
    window = PLAUSIBLE_WINDOWS.get(prayer.lower())
    if window is None:
        return value
    if _in_window(value, window):
        return value
    if value.hour < 12:
        shifted = time(hour=value.hour + 12, minute=value.minute)
        if _in_window(shifted, window):
            return shifted
    return value


def coerce_time(value: str, *, prayer: str | None = None) -> time | None:
    """Parse a loose time string and apply prayer-aware am/pm inference.

    This is the canonical entry point extractor scripts should use.
    """
    parsed = parse_time_loose(value)
    if parsed is None:
        return None
    return infer_ampm(parsed, prayer=prayer)
