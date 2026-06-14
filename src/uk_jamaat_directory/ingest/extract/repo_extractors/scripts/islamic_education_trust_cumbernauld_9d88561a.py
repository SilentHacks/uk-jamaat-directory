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
    key = "islamic_education_trust_cumbernauld_9d88561a"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("islamictrust.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="timetable_pdf",
            url="http://www.islamictrust.org/wp-content/uploads/2013/02/GCM-Timetable.pdf",
            kind=TargetKind.PDF,
        ),
    )
