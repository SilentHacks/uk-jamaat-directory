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
    key = "great_barr_muslim_foundation_b68365d4"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("gbmf.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer_timetable_page",
            url="https://gbmf.uk/prayer-timetable/",
            kind=TargetKind.HTML,
            requires_pdf=True,
        ),
    )
