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
    key = "masjid_al_furqan__leigh_mosque__d84092ee"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("masjidalfurqanleigh.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        now = datetime.now()
        month_name = now.strftime("%B").upper()
        url = (
            f"https://masjidalfurqanleigh.co.uk/web/siteAssets/site/"
            f"_360xAUTO_crop_center-center_none/{month_name}TIMETABLE{now.year}.png"
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
