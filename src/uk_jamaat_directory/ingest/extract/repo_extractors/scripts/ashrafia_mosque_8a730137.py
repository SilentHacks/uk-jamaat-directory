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
    key = "ashrafia_mosque_8a730137"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("ashrafiamasjid.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://ashrafiamasjid.org/",
            kind=TargetKind.HTML,
        ),
    )
