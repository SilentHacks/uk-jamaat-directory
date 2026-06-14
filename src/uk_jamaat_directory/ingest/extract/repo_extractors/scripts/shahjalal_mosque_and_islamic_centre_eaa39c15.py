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
    key = "shahjalal_mosque_and_islamic_centre_eaa39c15"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("shahjalalmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://shahjalalmosque.org/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("fajr", "zuhr")
    date_column = 0  # Use first column index as placeholder; we override parse_date_cell
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "zuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "magrib",
        Prayer.ISHA: "isha",
    }

    def accept_row(self, row: list[str], row_date: date) -> bool:
        # Only accept the "Jama'ah" row (jamaat times)
        if not row:
            return False
        first_cell = row[0].strip().lower()
        return "jama" in first_cell

    def parse_date_cell(self, value: str, *, year: int, month: int) -> date | None:
        # Always return today's date, ignoring the cell value
        return date.today()
