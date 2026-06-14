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
    key = "loughborough_mosque_and_islamic_cultural_association_8e5ce657"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("lboromasjid.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="annual timetable",
            url="https://lboromasjid.co.uk/wp-content/uploads/2025/12/Loughborough-mosque-2026-prayer-time-table_comp.pdf",
            kind=TargetKind.PDF,
        ),
    )
