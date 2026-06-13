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
    key = "piety_8981b761"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("piety.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)

    @property
    def targets(self):
        month = datetime.now().strftime("%b%Y")
        return (
            TargetSpec(
                label=f"monthly_timetable_{month}",
                url=f"http://piety.org.uk/wp-content/uploads/2026/01/{month}.pdf",
                kind=TargetKind.PDF,
            ),
        )
