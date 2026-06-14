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
    key = "the_abu_bakr_jamia_masjid_50fa3132"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("abubakrmasjid.net",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://abubakrmasjid.net/prayertimetable.aspx",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr jamaat",
        Prayer.DHUHR: "zhur jamaat",
        Prayer.ASR: "asr jamaat",
        Prayer.MAGHRIB: "maghrib jamaat",
        Prayer.ISHA: "isha jamaat",
    }
