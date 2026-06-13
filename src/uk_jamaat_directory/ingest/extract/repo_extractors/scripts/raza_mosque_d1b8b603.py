from datetime import datetime

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
    key = "raza_mosque_d1b8b603"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("razamasjidaston.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://razamasjidaston.co.uk/prayer-times/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = 0  # First column is date (day number)
    prayer_columns = {
        Prayer.FAJR: 4,  # FAJR Jamat column (0-indexed)
        Prayer.DHUHR: 6,  # ZUHR Jamat column
        Prayer.ASR: 8,  # ASR Jamat column
        Prayer.MAGHRIB: 9,  # MAGHRIB Jamat column
        Prayer.ISHA: 11,  # ISHA Jamat column
    }
