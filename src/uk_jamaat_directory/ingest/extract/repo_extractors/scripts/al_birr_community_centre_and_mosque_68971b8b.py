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
    key = "al_birr_community_centre_and_mosque_68971b8b"
    version = "2026.06.11.1"
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
    table_keywords = ("date", "fajr", "dhur")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr jamat",
        Prayer.DHUHR: "dhur jamat",
        Prayer.ASR: "asr jamat",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha jamat",
    }
