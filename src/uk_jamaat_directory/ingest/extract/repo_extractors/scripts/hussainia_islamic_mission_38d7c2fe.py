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
    key = "hussainia_islamic_mission_38d7c2fe"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("hussainiabradford.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer timetable pdf",
            url="https://hussainiabradford.com/wp-content/uploads/2025/12/Prayers-Time-Table-2026.pdf",
            kind=TargetKind.PDF,
        ),
    )
