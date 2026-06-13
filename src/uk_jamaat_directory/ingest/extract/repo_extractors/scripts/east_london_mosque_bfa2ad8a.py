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
    key = "east_london_mosque_bfa2ad8a"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("eastlondonmosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://eastlondonmosque.org.uk/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("gregorian date", "fajr jamā'ah")
    date_column = "gregorian date"
    prayer_columns = {
        Prayer.FAJR: "fajr jamā'ah",
        Prayer.DHUHR: "zuhr jamā'ah",
        Prayer.ASR: "asr jamā'ah",
        Prayer.MAGHRIB: "maghrib jamā'ah",
        Prayer.ISHA: "ishā jamā'ah",
    }
