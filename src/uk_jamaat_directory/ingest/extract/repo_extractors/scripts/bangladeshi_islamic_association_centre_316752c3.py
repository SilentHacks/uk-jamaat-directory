from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy, RunFrequency, SourceMatch, TargetKind, TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    TableTimetableExtractor,
)


class Extractor(TableTimetableExtractor):
    key = "bangladeshi_islamic_association_centre_316752c3"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("jms.org.uk", "www.jms.org.uk"))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://www.jms.org.uk/prayer-timetable/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "zuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
    }
