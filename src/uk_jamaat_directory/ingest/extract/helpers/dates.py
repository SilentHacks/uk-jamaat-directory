"""Date parsing helpers for extractor scripts.

Mosque timetables print dates in many shapes ("1", "01/06", "1 June",
"June 1 2026", "Mon 1st"). These helpers centralise the parsing so scripts
never hardcode month maps or years.
"""

from __future__ import annotations

import calendar
import re
from datetime import date

MONTHS: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_ORDINAL = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?", re.IGNORECASE)
_NUMERIC_DATE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?$")


def parse_month_name(value: str) -> int | None:
    cleaned = value.strip().lower().rstrip(".,")
    return MONTHS.get(cleaned)


def add_months(d: date, n: int) -> date:
    """Shift a date by *n* months, clamping the day to the month's end."""
    month_index = d.year * 12 + (d.month - 1) + n
    year, month = divmod(month_index, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def dates_for_month(year: int, month: int) -> list[date]:
    days = calendar.monthrange(year, month)[1]
    return [date(year, month, day) for day in range(1, days + 1)]


def parse_day_month(value: str, *, year: int) -> date | None:
    """Parse strings like "1 June", "June 1", "1st Jun"."""
    tokens = re.split(r"[\s,]+", value.strip())
    day: int | None = None
    month: int | None = None
    for token in tokens:
        if month is None:
            parsed_month = parse_month_name(token)
            if parsed_month is not None:
                month = parsed_month
                continue
        if day is None:
            m = _ORDINAL.fullmatch(token)
            if m:
                day = int(m.group(1))
    if day is None or month is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_date_flexible(value: str, *, default_year: int) -> date | None:
    """Parse common UK date shapes: "01/06/2026", "1/6", "1 June 2026",
    "June 1", "1st June". Day-first for numeric forms."""
    cleaned = value.strip()
    if not cleaned:
        return None
    m = _NUMERIC_DATE.match(cleaned)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year_raw = m.group(3)
        year = default_year
        if year_raw:
            year = int(year_raw)
            if year < 100:
                year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None
    year_match = re.search(r"(?<!\d)(20\d{2})(?!\d)", cleaned)
    year = int(year_match.group(1)) if year_match else default_year
    if year_match:
        cleaned = cleaned.replace(year_match.group(1), " ")
    return parse_day_month(cleaned, year=year)
