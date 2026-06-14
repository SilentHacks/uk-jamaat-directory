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
    key = "masjid_ilyas_790398c6"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("masjidilyas.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidilyas.org/wp-content/uploads/2026/04/05_May_timetable.pdf",
            kind=TargetKind.PDF,
        ),
    )
