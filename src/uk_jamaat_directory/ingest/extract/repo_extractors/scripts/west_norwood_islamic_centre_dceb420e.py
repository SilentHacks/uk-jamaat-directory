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
    key = "west_norwood_islamic_centre_dceb420e"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("westnorwoodmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/west-norwood-mosque",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("fajr", "asr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: "iqamah",
        Prayer.DHUHR: "iqamah",
        Prayer.ASR: "iqamah",
        Prayer.MAGHRIB: "athan",
        Prayer.ISHA: "athan",
    }
