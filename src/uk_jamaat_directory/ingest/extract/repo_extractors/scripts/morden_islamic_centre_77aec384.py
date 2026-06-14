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
    key = "morden_islamic_centre_77aec384"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("miconline.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://miconline.co.uk/monthly-salah-times",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        "fajr": "fajr",
        "dhuhr": "dhuhr",
        "asr": "asr",
        "maghrib": "maghrib",
        "isha": "isha",
    }
