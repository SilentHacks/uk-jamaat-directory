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
    key = "al_birr_80a0814a"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("albirr.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr jamat",
        Prayer.DHUHR: "dhur jamat",
        Prayer.ASR: "asr jamat",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha jamat",
    }

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        month_name = now.strftime("%B %Y")
        self.targets = (
            TargetSpec(
                label="timetable",
                url="http://albirr.com/Home/PrayerTime",
                kind=TargetKind.RENDERED_HTML,
                requires_javascript=True,
            ),
        )
