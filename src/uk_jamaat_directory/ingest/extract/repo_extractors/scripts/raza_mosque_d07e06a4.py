"""
Raza Mosque Lancaster prayer times extractor.
Target: MasjidBox embedded widget (JS-rendered).
"""

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
    key = "raza_mosque_d07e06a4"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("razamosquelancaster.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/raza-mosque",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("time", "prayer")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 1,
        Prayer.DHUHR: 2,
        Prayer.ASR: 3,
        Prayer.MAGHRIB: 4,
        Prayer.ISHA: 5,
    }
