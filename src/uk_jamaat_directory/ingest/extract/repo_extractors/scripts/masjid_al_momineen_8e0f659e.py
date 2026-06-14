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
    key = "masjid_al_momineen_8e0f659e"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("al-momineen.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)

    def __init__(self) -> None:
        now = datetime.now()
        month_url = (
            "https://www.al-momineen.org/wp-content/uploads/2025/12/"
            f"{now.strftime('%b%y')}-scaled.jpg"
        )
        self.targets = (
            TargetSpec(
                label="timetable",
                url=month_url,
                kind=TargetKind.IMAGE,
                requires_ocr=True,
            ),
        )
        super().__init__()
