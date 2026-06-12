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
    key = "masjid_mu_adh_ibn_jabal_bb6d0eb3"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("muadhibnjabal.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.muadhibnjabal.org/timetable",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
