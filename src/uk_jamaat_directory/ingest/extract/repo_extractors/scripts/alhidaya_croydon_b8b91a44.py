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
    key = "alhidaya_croydon_b8b91a44"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("alhidayacroydon.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer timetable",
            url="https://alhidayacroydon.org/s/Alhidaya-Prayer-Times-2026.pdf",
            kind=TargetKind.PDF,
            requires_pdf=True,
        ),
    )
