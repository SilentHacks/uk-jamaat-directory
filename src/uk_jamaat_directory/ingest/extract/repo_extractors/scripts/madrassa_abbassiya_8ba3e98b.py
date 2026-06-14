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
    key = "madrassa_abbassiya_8ba3e98b"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("abbasiya.wordpress.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://abbasiya.wordpress.com/",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
