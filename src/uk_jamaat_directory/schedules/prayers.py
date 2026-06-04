from __future__ import annotations

from datetime import date

from uk_jamaat_directory.domain import Prayer

PRAYER_ALIASES: dict[str, Prayer] = {
    "fajr": Prayer.FAJR,
    "dhuhr": Prayer.DHUHR,
    "zuhr": Prayer.DHUHR,
    "asr": Prayer.ASR,
    "maghrib": Prayer.MAGHRIB,
    "isha": Prayer.ISHA,
    "jumuah": Prayer.JUMUAH,
    "jumah": Prayer.JUMUAH,
    "jummah": Prayer.JUMUAH,
}

DAILY_PRAYERS = (
    Prayer.FAJR,
    Prayer.DHUHR,
    Prayer.ASR,
    Prayer.MAGHRIB,
    Prayer.ISHA,
)


def expected_prayers_for_date(on_date: date) -> set[Prayer]:
    prayers = set(DAILY_PRAYERS)
    if on_date.weekday() == 4:
        prayers.add(Prayer.JUMUAH)
    return prayers
