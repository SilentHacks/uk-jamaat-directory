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
    key = "masjid_e_usman_c00e17b7"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("masjid-e-usman.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjid-e-usman.co.uk/",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
