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
    key = "darul_ihsaan_barking_f1d2fd62"
    version = "2026.06.11.1"
    source_match = SourceMatch(
        domains=("darulihsaanbarking.org.uk", "darulihsaan.org.uk"),
    )
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://darulihsaanbarking.org.uk/prayer-times/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("date", "jama'at")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 4,
        Prayer.ASR: 6,
        Prayer.MAGHRIB: 8,
        Prayer.ISHA: 10,
    }
