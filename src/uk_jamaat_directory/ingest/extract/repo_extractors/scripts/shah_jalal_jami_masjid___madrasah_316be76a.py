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
    key = "shah_jalal_jami_masjid___madrasah_316be76a"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("shahjalal.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.shahjalal.org/timetable",
            kind=TargetKind.PDF,
        ),
    )
