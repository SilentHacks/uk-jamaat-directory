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
    key = "taiba_welfare_foundation_0b62d1dc"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("taibafoundation.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer_timetable",
            url="https://taibafoundation.org/wp-content/uploads/2026/05/May-2026-TIME-TABLE-Taiba.pdf",
            kind=TargetKind.PDF,
        ),
    )
