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
    key = "jamia_masjid_azmat_e_islam_d37f1db9"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("ukimoldham.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # The site publishes monthly prayer timetables as PDFs under /prayer-times/.
        # Each month links to a PDF at /wp-content/uploads/2014/09/MONTH.pdf
        # (note: year in path is static 2014, but PDFs are current).
        # No HTML table or jamaat-specific times are on the site.
        # Declare as PDF target (stubbed; parser implementation pending).
        now = datetime.now()
        month_name = now.strftime("%B")
        url = f"http://ukimoldham.org.uk/wp-content/uploads/2014/09/{month_name}.pdf"
        self.targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )
