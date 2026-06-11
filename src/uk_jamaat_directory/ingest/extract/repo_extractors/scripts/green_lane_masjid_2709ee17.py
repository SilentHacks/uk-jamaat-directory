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
    key = "green_lane_masjid_2709ee17"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("greenlanemasjid.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://greenlanemasjid.org/wp-content/uploads/2026/05/GLM-SALAH-TIMETABLE-JUNJUL26.pdf",
            kind=TargetKind.PDF,
            requires_ocr=True,
        ),
    )
