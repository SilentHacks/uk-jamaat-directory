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
    key = "stepney_shahjalal_mosque___cultural_centre_c11f557d"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("stepneyshahjalalmosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://stepneyshahjalalmosque.org.uk/full-year-timetable",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("day", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 5,
        Prayer.ASR: 7,
        Prayer.MAGHRIB: 9,
        Prayer.ISHA: 11,
    }
