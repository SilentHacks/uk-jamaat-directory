from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    TableTimetableExtractor,
)


class Extractor(TableTimetableExtractor):
    key = "hull_mosque_63dcbfb3"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("hullmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 5,
        Prayer.ASR: 7,
        Prayer.MAGHRIB: 9,
        Prayer.ISHA: 11,
    }

    def __init__(self) -> None:
        super().__init__()
        month = datetime.now().month
        self.targets = (
            TargetSpec(
                label="timetable",
                url=f"https://hullmosque.com/prayer-times/page/{month}/",
                kind=TargetKind.HTML,
            ),
        )

    def clean_cell(self, value: str) -> str:
        v = value.strip()
        # Normalize "01-Jan", "15-Feb" (and similar) to "01 Jan" so the
        # flexible date parser can recognise the bare day + month abbreviation.
        m = re.match(r"^(\d{1,2})[-–—](\w{3,9})$", v, re.IGNORECASE)
        if m:
            return f"{m.group(1)} {m.group(2)}"
        return v
