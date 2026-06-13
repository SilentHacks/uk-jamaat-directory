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
    key = "dartford_masjid_6357c7ae"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("dmic.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://dmic.co.uk/Prayer-Times/Monthly-Prayer-Timetable-June-2026.pdf",
            kind=TargetKind.PDF,
            requires_pdf=True,
        ),
    )
