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
    key = "majid_e_usmani_a9c0667f"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("usmanimosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)

    @property
    def targets(self):
        """Build month-specific PDF URL from current date."""
        now = datetime.now()
        month_name = now.strftime("%B")
        year = now.year
        month_idx = now.month - 1
        return (
            TargetSpec(
                label="timetable",
                url=f"https://usmanimosque.com/wp-content/uploads/{year}/{month_idx:02d}/{month_name}.pdf",
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )
