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
    key = "boston_mosque___islamic_centre_45c615a8"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("bostonmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="monthly_timetable",
            url="https://bostonmosque.org/prayer-timings/",
            kind=TargetKind.PDF,
        ),
    )
