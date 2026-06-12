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
    key = "jamiat_ahle_e_hadith_masjid_c9d0ea1b"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("web.archive.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://web.archive.org/web/20161124123516/http://www.greenlanemasjid.org/Prayer-Times.aspx",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("fajr", "jamat")
    date_column = 1
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 8,
        Prayer.MAGHRIB: 9,
        Prayer.ISHA: 11,
    }
