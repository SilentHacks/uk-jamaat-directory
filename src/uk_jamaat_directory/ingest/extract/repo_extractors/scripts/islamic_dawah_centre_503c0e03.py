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
    key = "islamic_dawah_centre_503c0e03"
    version = "2026.06.13.2"
    source_match = SourceMatch(domains=("idcuk.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer timetable PDF",
            url="https://idcuk.org/demo/prayer-times/",
            kind=TargetKind.HTML,
        ),
    )
