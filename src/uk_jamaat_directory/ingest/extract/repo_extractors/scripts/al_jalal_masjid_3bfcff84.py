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
    key = "al_jalal_masjid_3bfcff84"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("aljalalmasjid.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        month_name = datetime.now().strftime("%B").lower()
        self.targets = (
            TargetSpec(
                label="timetable",
                url=f"https://aljalalmasjid.org/prayer/{month_name}/",
                kind=TargetKind.HTML,
            ),
        )

    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr jamat",
        Prayer.DHUHR: "zuhr jamat",
        Prayer.ASR: "asr jamat",
        Prayer.MAGHRIB: "maghrib jamat",
        Prayer.ISHA: "isha jamat",
    }
