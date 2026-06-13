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
    key = "eccles_mosque_5c3b4a54"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("ecclesmosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="monthly_prayer_timetable",
            url="http://ecclesmosque.org.uk/",
            kind=TargetKind.PDF,
        ),
    )
