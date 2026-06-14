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
    key = "oldham_madani_academy_fe1265b3"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("oldhammadaniacademy.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # The site publishes the authoritative monthly timetable as a PNG image
        # (e.g. 06-OMA-Timetable-June-2026-scaled.png) under /wp-content/uploads/YYYY/01/.
        # The homepage and /timetable/ embed this image; no HTML table or text
        # jamaat schedule is present. Declare as IMAGE target (stubbed; OCR later).
        # Build the month-specific URL from the current date (no hardcoded year).
        now = datetime.now()
        month_name = now.strftime("%B")
        mnum = now.strftime("%m")
        url = (
            f"https://oldhammadaniacademy.org.uk/wp-content/uploads/"
            f"{now.year}/01/{mnum}-OMA-Timetable-{month_name}-{now.year}-scaled.png"
        )
        self.targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.IMAGE,
                requires_ocr=True,
            ),
        )
