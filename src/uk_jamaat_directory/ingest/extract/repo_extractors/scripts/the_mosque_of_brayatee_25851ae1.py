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
    key = "the_mosque_of_brayatee_25851ae1"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("mosqueofbrayatee.weebly.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://mosqueofbrayatee.weebly.com/prayer.html",
            kind=TargetKind.IMAGE,
        ),
    )
