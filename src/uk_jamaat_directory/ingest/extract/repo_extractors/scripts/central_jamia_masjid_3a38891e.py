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
    key = "central_jamia_masjid_3a38891e"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("mkcjm.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://mkcjm.org.uk/?page_id=78",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr jamah",
        Prayer.DHUHR: "zuhr jamah",
        Prayer.ASR: "asr jamah",
        Prayer.MAGHRIB: "maghrib jamah",
        Prayer.ISHA: "isha jamah",
    }
