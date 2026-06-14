import re
from datetime import date

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
    key = "as_salam_centre_5ebfff08"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("as-salaam.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://as-salaam.org/timetable",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 3,
        Prayer.ASR: 4,
        Prayer.MAGHRIB: 5,
        Prayer.ISHA: 6,
    }

    def clean_cell(self, value: str) -> str:
        """Extract jamaat time from cell containing 'jamaat AMBegins start AM'."""
        if not value:
            return ""
        val = value.strip()
        # Try to extract time from format like "4:10 AMBegins 2:35 AM"
        m = re.search(r"(\d{1,2}:\d{2}\s*(?:am|pm)?)", val, re.IGNORECASE)
        if m:
            return m.group(1)
        # Not a time cell, return as-is
        return val

    def accept_row(self, row: list[str], row_date: date) -> bool:
        return True
