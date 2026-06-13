"""
Sutton Coldfield Muslim Association prayer timetable extractor.
Target: PDF monthly timetable (requires OCR/parsing).
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
    key = "sutton_coldfield_muslim_association_3ad1c7e9"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("suttonmuslims.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="monthly_timetable",
            url="http://suttonmuslims.org.uk/resources/Sutton-Coldfield-Masjid-(0626).pdf",
            kind=TargetKind.PDF,
        ),
    )
