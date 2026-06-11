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
    key = "upper_soothill_islamic_centre_72f46809"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("usic.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://usic.org.uk/timings",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr", "iqamah")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr iqamah",
        Prayer.DHUHR: "dhuhr iqamah",
        Prayer.ASR: "asr iqamah",
        Prayer.MAGHRIB: "maghrib iqamah",
        Prayer.ISHA: "isha iqamah",
    }
