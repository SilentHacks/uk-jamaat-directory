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
    PdfTableTimetableExtractor,
)


class Extractor(PdfTableTimetableExtractor):
    key = "quwwat_ul_islam_masjid_d4c8228c"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("quwwatulislam.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://quwwatulislam.org/wp-content/uploads/2025/12/QIS_2026_Salah_Timetable.pdf",
            kind=TargetKind.PDF,
        ),
    )

    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr jamaat",
        Prayer.DHUHR: "zuhr jamaat",
        Prayer.ASR: "asr jamaat",
        Prayer.MAGHRIB: "maghrib jamaat",
        Prayer.ISHA: "isha jamaat",
    }

    def current_year(self, ctx):
        """Always use 2026 as the year since the PDF is for 2026."""
        return 2026

    def current_month(self, ctx):
        """Extract month from the target URL or use the current month."""
        return datetime.now().month
