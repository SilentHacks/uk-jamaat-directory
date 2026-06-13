"""
Extractor for Galler Turkish Mosque (Suleymaniye Mosque, London).
Source loads prayer times dynamically via JavaScript.
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
    key = "galler_turkish_mosque_b70d3ed7"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("suleymaniye.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://suleymaniye.org/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "dhuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
    }
