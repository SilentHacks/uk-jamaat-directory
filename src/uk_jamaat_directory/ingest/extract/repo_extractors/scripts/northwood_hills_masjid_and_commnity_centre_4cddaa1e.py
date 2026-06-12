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
    key = "northwood_hills_masjid_and_commnity_centre_4cddaa1e"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("ironaid.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://ironaid.org/wp-content/uploads/2025/07/LondonPrayerTimes-2025-08-250718-1-pdf.jpg",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
