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
    key = "greengate_jamia_mosque_6b5e5a01"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("greengatejamiamasjid.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self):
        now = datetime.now()
        month_name = now.strftime("%B").upper()
        year = now.year
        pdf_filename = f"{month_name}-{year}.pdf"
        url = f"https://greengatejamiamasjid.co.uk/assets/files/{pdf_filename}"
        self.targets = (
            TargetSpec(
                label="prayer timetable",
                url=url,
                kind=TargetKind.PDF,
            ),
        )
