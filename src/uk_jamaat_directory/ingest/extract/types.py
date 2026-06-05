from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time

from uk_jamaat_directory.domain import Prayer


@dataclass(frozen=True)
class ExtractedScheduleRow:
    date: date
    prayer: Prayer
    jamaat_time: time
    start_time: time | None
    session_number: int
    session_label: str | None
    timezone: str


@dataclass
class ExtractResult:
    rows: list[ExtractedScheduleRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    extractor_version: str = ""
