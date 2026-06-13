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
    key = "masjid_al_ummah_7f351bc0"
    version = "2026.06.12.1"
    source_match = SourceMatch(
        domains=("abrahamicfoundation.org.uk", "legacy.abrahamicfoundation.org.uk")
    )
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # Verified: no HTML timetable or embedded widget on domain.
        # Broadest timetable is the monthly PDF linked from /services/masjid/salah-prayers/
        # (page advertises "May Salah Timetable 2026" at time of authoring; URL is the one visited).
        # Use StubbedPdfExtractor per rules (do not parse PDF here; stub records target).
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://legacy.abrahamicfoundation.org.uk/wp-content/uploads/2020/08/05-May-Salah-Timetable-Masjid-al-Ummah-1.pdf",
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )
