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
    key = "masjid_e_zeenat_ul_islam_a71f8943"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("masjidzeenatulislam.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # The site publishes its prayer timetable as a bi-monthly PDF (and matching images).
        # The /timetable/ page embeds the images and links the PDF; no full HTML table of
        # the schedule is present. Target the current published PDF directly.
        # New bi-monthly PDFs will require a script update + version bump when released.
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://masjidzeenatulislam.org.uk/wp-content/uploads/2026/04/Bi-Monthly_TimeTable_03_May_Jun_2026.pdf",
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )
