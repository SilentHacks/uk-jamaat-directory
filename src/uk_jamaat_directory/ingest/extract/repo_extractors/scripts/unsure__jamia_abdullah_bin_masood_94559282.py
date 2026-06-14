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
    key = "unsure__jamia_abdullah_bin_masood_94559282"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("jabm.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.jabm.co.uk/",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
