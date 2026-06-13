from datetime import datetime

from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    StubbedPdfExtractor,
)


class Extractor(StubbedPdfExtractor):
    key = "masjid_adam_5d5ccd86"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("masjidadam.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # Monthly PDF timetable published under /uploads/YYYY/MM/Month-YYYY_compressed.pdf
        # Build the current month's target URL (no hard-coded year/month).
        now = datetime.now()
        month_name = now.strftime("%B")
        url = (
            f"https://masjidadam.co.uk/wp-content/uploads/"
            f"{now.year}/{now.month:02d}/{month_name}-{now.year}_compressed.pdf"
        )
        self.targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )
