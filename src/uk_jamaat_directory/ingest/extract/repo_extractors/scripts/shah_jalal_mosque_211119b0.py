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
    key = "shah_jalal_mosque_211119b0"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("chestermosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://chestermosque.org/prayer-timetable/",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
