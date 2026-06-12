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
    key = "masjid_daar_al_hadeeth_9fe0dfd4"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("daarhadeeth.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        now = datetime.now()
        month_name = now.strftime("%B")
        url = (
            f"https://daarhadeeth.com/wp-content/uploads/"
            f"{now.year}/{now.month:02d}/{month_name}-{now.year}-Instagram-size-scaled.png"
        )
        self.targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.IMAGE,
                requires_ocr=True,
            ),
        )
        super().__init__()
