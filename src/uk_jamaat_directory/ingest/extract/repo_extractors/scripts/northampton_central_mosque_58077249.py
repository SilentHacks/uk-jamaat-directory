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
    key = "northampton_central_mosque_58077249"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("ncmosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer_times_pdf",
            url="http://www.ncmosque.co.uk/Prayer.pdf",
            kind=TargetKind.PDF,
            requires_pdf=True,
        ),
    )
