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
    key = "muslim_cultural_and_welfare_association_of_sutton_32e2b621"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("mcwas.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.mcwas.org/s/MCWAS-Calendar-2026-LR.pdf",
            kind=TargetKind.PDF,
            requires_pdf=True,
        ),
    )
