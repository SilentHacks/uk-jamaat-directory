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
    key = "ilford_mosque_8fcfbb9d"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("ilfordmuslimsociety.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)

    def __init__(self):
        # Build current month PDF URL
        month_name = datetime.now().strftime("%B").lower()
        url = f"http://ilfordmuslimsociety.org/salaat_times/{month_name}.pdf"
        self.targets = (
            TargetSpec(
                label="monthly_timetable",
                url=url,
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )
