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
    key = "manchester_islamic_centre___didsbury_mosque_70eec6a8"
    version = "2026.06.18.1"
    source_match = SourceMatch(domains=("didsburymosque.com", "didsburymosque.org"))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://didsburymosque.org/prayer-times",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("day", "fajr")
    date_column = 1
    prayer_columns = {
        Prayer.FAJR: 4,
        Prayer.DHUHR: 7,
        Prayer.ASR: 9,
        Prayer.MAGHRIB: 11,
        Prayer.ISHA: 12,
    }
