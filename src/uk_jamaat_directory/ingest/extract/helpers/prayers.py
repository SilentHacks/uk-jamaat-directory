from __future__ import annotations

import re
from datetime import time

from uk_jamaat_directory.domain import Prayer

PRAYER_KEYWORDS: dict[Prayer, tuple[str, ...]] = {
    Prayer.FAJR: ("fajr", "fajar", "sehri", "suhoor", "subh"),
    Prayer.DHUHR: ("dhuhr", "zuhr", "zohar", "zohr", "thuhr", "thuhur"),
    Prayer.ASR: ("asr", "asar"),
    Prayer.MAGHRIB: ("maghrib", "maghrebin", "magrib", "iftaar", "iftar"),
    Prayer.ISHA: ("isha", "ishaa", "esha", "eshaa", "night"),
    Prayer.JUMUAH: ("jumuah", "jumma", "jummah", "jumah", "friday"),
}


def parse_prayer_label(value: str) -> Prayer | None:
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    for prayer, keywords in PRAYER_KEYWORDS.items():
        for keyword in keywords:
            if keyword in cleaned:
                return prayer
    return None


def is_jumuah_label(value: str) -> bool:
    prayer = parse_prayer_label(value)
    return prayer == Prayer.JUMUAH
