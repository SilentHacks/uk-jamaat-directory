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
    key = "nottingham_islam_information_point_ea617300"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("nottinghamislam.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://nottinghamislam.com/",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
