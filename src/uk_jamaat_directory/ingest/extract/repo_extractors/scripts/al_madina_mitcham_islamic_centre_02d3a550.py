from datetime import datetime

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
    key = "al_madina_mitcham_islamic_centre_02d3a550"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("almadina.cfsites.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)

    def __init__(self) -> None:
        month_name = datetime.now().strftime("%B").lower()
        self.targets = (
            TargetSpec(
                label="timetable",
                url=f"http://almadina.cfsites.org/files/{month_name}timetable.png",
                kind=TargetKind.IMAGE,
                requires_ocr=True,
            ),
        )
        super().__init__()
