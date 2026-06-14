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
    key = "al_ansar_islamic_education_centre_841c66b8"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("masjidansar.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://masjidansar.com/pray/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr jamat")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr jamat",
        Prayer.DHUHR: "dhuhr jamat",
        Prayer.ASR: "asr jamat",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha jamat",
    }
