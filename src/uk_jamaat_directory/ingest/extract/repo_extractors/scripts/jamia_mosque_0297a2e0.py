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
    key = "jamia_mosque_0297a2e0"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("huntingdonjamiamosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # The site links from the homepage to /prayer-timetable.html which embeds
        # a month-specific image timetable (e.g. JuneTimetable.jpg). No HTML table
        # or text jamaat schedule is present on the site; the authoritative
        # timetable is the JPEG image. Declare as IMAGE target (stubbed; OCR later).
        # Build the month-specific URL from the current date (no hardcoded year).
        now = datetime.now()
        month_name = now.strftime("%B")
        url = f"https://huntingdonjamiamosque.com/{month_name}Timetable.jpg"
        self.targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.IMAGE,
                requires_ocr=True,
            ),
        )
