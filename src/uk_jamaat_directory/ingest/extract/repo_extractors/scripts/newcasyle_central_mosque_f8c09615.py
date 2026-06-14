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
    key = "newcasyle_central_mosque_f8c09615"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("newcastlecentralmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://newcastlecentralmosque.com/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("prayer", "jamaat", "begin")
    date_column = None
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "dhuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
    }

    def extract_date_from_page(self, artifact_content: str) -> datetime.date:
        """Extract date from rendered page."""
        return datetime.now().date()

    def accept_row(self, cells, row_index):
        """Accept prayer rows only."""
        if not cells or len(cells) < 2:
            return False
        prayer_name = cells[0].lower().strip()
        # Include only the five daily prayers
        allowed = {"fajr", "dhuhr", "asr", "maghrib", "isha"}
        return prayer_name in allowed

