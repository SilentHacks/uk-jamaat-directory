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
    key = "masjid_quba_ead9bf56"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("healeyislamictrust.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.healeyislamictrust.co.uk/salaah-times/",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
