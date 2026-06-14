from datetime import datetime, timedelta
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
from uk_jamaat_directory.ingest.extract.helpers.html import find_table


class Extractor(TableTimetableExtractor):
    key = "asha_islamic_centre_e1ed207a"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("ashacentre.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://ashacentre.co.uk/calender/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    
    table_keywords = ("date", "fajr", "dhuhr")
    date_column = "date"
    target_label = "timetable"
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "dhuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
    }
