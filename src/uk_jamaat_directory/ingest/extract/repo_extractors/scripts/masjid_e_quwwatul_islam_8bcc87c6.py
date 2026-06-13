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
    key = "masjid_e_quwwatul_islam_8bcc87c6"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("masjidquwwatulislam.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidquwwatulislam.co.uk/",
            kind=TargetKind.RENDERED_HTML,
        ),
    )
    table_keywords = ("fajr", "dhuhr", "asr", "maghrib", "isha", "iqamah")
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "dhuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
    }
