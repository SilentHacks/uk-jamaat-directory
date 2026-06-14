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
    key = "east_london_mosque___london_muslim_centre_2cb02a69"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("eastlondonmosque.org.uk", "www.eastlondonmosque.org.uk"))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.eastlondonmosque.org.uk/prayer-times",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 6,
        Prayer.DHUHR: 8,
        Prayer.ASR: 11,
        Prayer.MAGHRIB: 13,
        Prayer.ISHA: 15,
    }
