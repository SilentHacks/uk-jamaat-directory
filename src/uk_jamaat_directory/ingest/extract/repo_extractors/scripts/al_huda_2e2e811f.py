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
    key = "al_huda_2e2e811f"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("al-huda.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        year = datetime.now().year
        self.targets = (
            TargetSpec(
                label="timetable",
                url=f"http://al-huda.org.uk/uploads/5/7/1/2/57121291/al_huda_timetable_{year}.pdf",
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )
