from __future__ import annotations

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
    key = "exeter_mosque_2aad1d84"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("exetermosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://exetermosque.org.uk/timetable/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr iqamah",
        Prayer.DHUHR: "dhuhr iqamah",
        Prayer.ASR: "asr iqamah",
        Prayer.MAGHRIB: "maghrib iqamah",
        Prayer.ISHA: "isha iqamah",
    }
