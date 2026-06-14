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
    key = "north_jamia_watford_mosque_246a96ea"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("watfordmosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer timetable image",
            url="http://watfordmosque.org.uk/prayer-timetable",
            kind=TargetKind.IMAGE,
        ),
    )
