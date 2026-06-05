from __future__ import annotations

import re
from dataclasses import dataclass

from uk_jamaat_directory.ingest.sources.muslimsinbritain.schema import (
    MibConfidence,
    MibRecordClass,
    MibTriState,
    MibUsage,
)

THEME_CODES = {
    "Arab": "Arab mainstream",
    "Deob": "Deobandi",
    "Maud": "Maudoodi",
    "Salf": "Salafi",
    "Shia": "Shia",
    "Brel": "Bareilvi",
    "Sufi": "Sufi",
}

MANAGEMENT_CODES = {
    "Arab": "Arab",
    "Bang": "Bangladeshi",
    "Guje": "Gujerati",
    "Paki": "Pakistani",
    "Pkstn": "Pakistani",
    "Stud": "Students",
    "Stdnt": "Students",
    "Tami": "Tamil",
    "Turk": "Turkish",
}

_CAPACITY = re.compile(r"^(\d+)")


@dataclass(frozen=True)
class MibInfoCode:
    capacity: int | None = None
    women_facilities: MibTriState = "unknown"
    usage: MibUsage = "unknown"
    record_class: MibRecordClass = "mosque"
    metadata_confidence: MibConfidence = "high"
    theme: str | None = None
    management: str | None = None


def decode_info_code(raw: str | None) -> MibInfoCode:
    if raw is None:
        return MibInfoCode(metadata_confidence="unknown")

    text = raw.strip()
    metadata_confidence: MibConfidence = "high"
    if text.startswith("?"):
        metadata_confidence = "low"
        text = text[1:]

    capacity = None
    match = _CAPACITY.match(text)
    if match:
        capacity = int(match.group(1))
        text = text[match.end() :]

    women_facilities: MibTriState = "unknown"
    if text.startswith("NoW"):
        women_facilities = "no"
        text = text[3:]
    elif text.startswith("W"):
        women_facilities = "yes"
        text = text[1:]

    usage: MibUsage = "full_time"
    record_class: MibRecordClass = "mosque"
    lowered = text.lower()
    if lowered.startswith("multi"):
        usage = "unknown"
        record_class = "multi_faith"
        text = text[5:]
    elif text.startswith("Irreg"):
        usage = "irregular"
        record_class = "prayer_room"
        text = text[5:]
    elif text.startswith("NJ"):
        usage = "no_jumuah"
        text = text[2:]
    elif text.startswith("J"):
        usage = "jumuah_only"
        record_class = "hired_hall"
        text = text[1:]

    theme, text = _consume_code(text, THEME_CODES)
    management, _text = _consume_code(text, MANAGEMENT_CODES)
    return MibInfoCode(
        capacity=capacity,
        women_facilities=women_facilities,
        usage=usage,
        record_class=record_class,
        metadata_confidence=metadata_confidence,
        theme=theme,
        management=management,
    )


def _consume_code(text: str, mapping: dict[str, str]) -> tuple[str | None, str]:
    for code in sorted(mapping, key=len, reverse=True):
        if text.startswith(code):
            return mapping[code], text[len(code) :]
    return None, text
