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
    key = "mid_sussex_islamic_centre_and_masjid_14534a5b"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("haywardsheathmosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # The site provides a "Timetable" dropdown linking to monthly image
        # timetables (e.g. /assets/images/timetables/june.webp). These are the
        # broadest schedules (monthly > the homepage's today-only snapshot).
        # The homepage table shows explicit Iqamah/Jamaat times (not just adhan),
        # but is a single-day view without a date column and is not the persistent
        # schedule. The monthly images are the authoritative timetables and are
        # served as images, so declare an IMAGE target (stubbed; OCR later).
        # Build the month-specific URL from the current date (no hardcoded year).
        now = datetime.now()
        month_name = now.strftime("%B").lower()
        url = f"http://haywardsheathmosque.co.uk/assets/images/timetables/{month_name}.webp"
        self.targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.IMAGE,
                requires_ocr=True,
            ),
        )
