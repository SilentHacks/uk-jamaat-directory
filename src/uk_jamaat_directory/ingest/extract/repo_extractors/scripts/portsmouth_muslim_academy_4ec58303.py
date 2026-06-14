from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.relative import jamaat_after_start
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
    key = "portsmouth_muslim_academy_4ec58303"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("portsmouth-muslim-academy.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    target_label = "timetable"
    targets = (
        TargetSpec(
            label="timetable",
            url="https://portsmouth-muslim-academy.org/prayer-times",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("Bayan Start", "Jamat")
    date_column = 0

    prayer_columns = {
        Prayer.JUMUAH: "Jamat",
    }

    def accept_row(self, cells):
        """Accept only Summer and Winter rows."""
        if not cells:
            return False
        first_cell = cells[0].strip().lower()
        return first_cell in ("summer", "winter")

    def clean_cell(self, value):
        """Clean cell values."""
        return value.strip()
