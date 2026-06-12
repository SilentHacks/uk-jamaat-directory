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
    key = "islamic_centre_of_england_af3255b3"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("ic-el.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        now = datetime.now()
        month_name = now.strftime("%B")
        year = now.year
        url = (
            f"http://ic-el.com/wp-content/icel/praying_timetable/tables/"
            f"Timetable-London-{month_name}{year}-en.jpg"
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
