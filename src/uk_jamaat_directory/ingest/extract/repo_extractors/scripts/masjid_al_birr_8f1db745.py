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
    key = "masjid_al_birr_8f1db745"
    version = "2026.06.16.1"
    source_match = SourceMatch(domains=("albirr.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://albirr.com/Home/PrayerTime",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr jamat",
        Prayer.DHUHR: "dhur jamat",
        Prayer.ASR: "asr jamat",
        Prayer.MAGHRIB: "maghrib jamat",
        Prayer.ISHA: "isha jamat",
    }
