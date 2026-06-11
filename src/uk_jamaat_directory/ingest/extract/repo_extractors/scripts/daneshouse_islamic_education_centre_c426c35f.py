from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    StubbedOcrExtractor,
)


class Extractor(StubbedOcrExtractor):
    key = "daneshouse_islamic_education_centre_c426c35f"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("diec.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.diec.org.uk/_files/ugd/0fafe2_0ad7517d0dd744199bcd52c6babaaaf6.pdf",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
