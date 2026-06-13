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
    key = "al_huda_welfare_foundation_uk_ae9801e4"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("alhudauk.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://alhudauk.com/services/prayer/screen",
            kind=TargetKind.RENDERED_HTML,
        ),
    )
    table_keywords = ("prayer", "iqamah")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 2,
        Prayer.ASR: 2,
        Prayer.MAGHRIB: 2,
        Prayer.ISHA: 2,
    }

    def accept_row(self, row_data):
        if not row_data or len(row_data) < 1:
            return False
        prayer_name = (row_data[0] or "").strip().lower()
        if prayer_name in ("jumu'ah", "jumuah", "sunrise"):
            return False
        return prayer_name in ("fajr", "dhohr", "asr", "maghrib", "isha")

    def clean_cell(self, cell_text, is_date_col=False):
        text = (cell_text or "").strip()
        if is_date_col:
            today_str = datetime.now().strftime("%a %d %b").lower()
            if today_str in text.lower():
                return datetime.now().strftime("%Y-%m-%d")
        return text
