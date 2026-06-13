from datetime import datetime
from uk_jamaat_directory.domain import Prayer
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
    key = "jalalia_jamme_masjeed_f5b5e17f"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("jjme.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer_timetable_pdf",
            url="https://www.jjme.org/masjid/wp-content/uploads/2025/01/PDF-calendar.pdf",
            kind=TargetKind.PDF,
        ),
    )
