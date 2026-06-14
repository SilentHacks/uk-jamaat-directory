from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy, RunFrequency, SourceMatch, TargetKind, TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    StubbedPdfExtractor,
)


class Extractor(StubbedPdfExtractor):
    key = "al_baseera_bristol_centre_1111ce17"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("albaseera.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://albaseera.org/wp-content/uploads/2026/05/June-2026.pdf",
            kind=TargetKind.PDF,
            requires_pdf=True,
        ),
    )
