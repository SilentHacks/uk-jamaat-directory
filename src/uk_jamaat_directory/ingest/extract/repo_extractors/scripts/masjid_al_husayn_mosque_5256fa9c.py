"""
Masjid Al-Husayn Mosque timetable extractor.
Extracts prayer times from monthly PDF timetables.
"""

from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    StubbedPdfExtractor,
)


class Extractor(StubbedPdfExtractor):
    key = "masjid_al_husayn_mosque_5256fa9c"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("mksileicester.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="monthly_timetable",
            url="https://www.mksileicester.org/resources/namaaz-times/",
            kind=TargetKind.PDF,
        ),
    )
