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
    key = "aberdeen_mosque_and_islamic_centre_0477ea2b"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("aberdeenmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://aberdeenmosque.org/prayer-times-central",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr jamā'ah",
        Prayer.DHUHR: "zuhr jamā'ah",
        Prayer.ASR: "asr jamā'ah",
        Prayer.MAGHRIB: "maghrib jamā'ah",
        Prayer.ISHA: "ishā jamā'ah",
    }
