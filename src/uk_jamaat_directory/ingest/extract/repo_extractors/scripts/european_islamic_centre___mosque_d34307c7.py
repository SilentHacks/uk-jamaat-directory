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
    key = "european_islamic_centre___mosque_d34307c7"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("ukimoldham.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        month_name = now.strftime("%B")
        url = (
            f"https://www.ukimoldham.org.uk/wp-content/uploads/"
            f"{now.year}/{now.month:02d}/UKIM-Oldham-{month_name}-{now.year}.pdf"
        )
        self.targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )
