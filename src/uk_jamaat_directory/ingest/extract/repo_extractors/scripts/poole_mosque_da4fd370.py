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
    key = "poole_mosque_da4fd370"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("poolemosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="monthly_timetable",
            url="https://poolemosque.co.uk/timetable",
            kind=TargetKind.PDF,
        ),
    )
