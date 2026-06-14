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
    key = "rugby_mosque_b1bc45a9"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("rugby-mosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://rugby-mosque.org/prayer-times/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr jamat",
        Prayer.DHUHR: "dhuhr jamat",
        Prayer.ASR: "asr jamat",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha jamat",
    }
