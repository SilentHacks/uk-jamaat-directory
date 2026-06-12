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
    key = "northampton_mosque_and_islamic_centre_39cb3810"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("northamptonislamiccentre.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://northamptonislamiccentre.com/timetable/",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
