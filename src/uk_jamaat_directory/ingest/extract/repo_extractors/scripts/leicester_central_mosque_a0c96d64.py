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
    key = "leicester_central_mosque_a0c96d64"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("islamiccentre.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://islamiccentre.org/component/kaprayertimes/prayertimes",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr jamaat",
        Prayer.DHUHR: "dhuhr jamaat",
        Prayer.ASR: "asr jamaat",
        Prayer.MAGHRIB: "maghrib jamaat",
        Prayer.ISHA: "isha jamaat",
    }
