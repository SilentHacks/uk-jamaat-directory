"""
Luton Central Mosque prayer timetable extractor.

Target: PDF monthly timetable
URL: https://lutoncentralmosque.org/wp-content/uploads/2026/06/June-26.pdf
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
    key = "luton_central_mosque_558d021d"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("lutoncentralmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="monthly_pdf_timetable",
            url="https://lutoncentralmosque.org/prayer-times/",
            kind=TargetKind.PDF,
        ),
    )
