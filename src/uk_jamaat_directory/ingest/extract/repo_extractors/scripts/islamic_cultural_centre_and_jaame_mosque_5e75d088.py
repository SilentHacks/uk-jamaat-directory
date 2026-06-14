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
    key = "islamic_cultural_centre_and_jaame_mosque_5e75d088"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("jaamemasjid.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="monthly timetable",
            url="https://www.jaamemasjid.org/wp-content/uploads/2026/01/IMG-20260101-WA0006.jpg",
            kind=TargetKind.IMAGE,
        ),
    )
