from datetime import datetime
from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy, RunFrequency, SourceMatch, TargetKind, TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    TableTimetableExtractor,
)


class Extractor(TableTimetableExtractor):
    key = "north_finchley_mosque_ea4bee7c"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("ianl.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://ianl.org.uk/monthly-prayer-times/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("day", "fajr", "dhuhr", "asr", "maghrib", "ishaa")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: "fajr jamaat",
        Prayer.DHUHR: "dhuhr jamaat",
        Prayer.ASR: "asr jamaat",
        Prayer.MAGHRIB: "maghrib jamaat",
        Prayer.ISHA: "ishaa jamaat",
    }
