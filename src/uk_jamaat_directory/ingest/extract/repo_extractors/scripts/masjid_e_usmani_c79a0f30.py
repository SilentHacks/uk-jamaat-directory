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
    key = "masjid_e_usmani_c79a0f30"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("usmanimosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="monthly-timetable",
            url=f"https://usmanimosque.com/wp-content/uploads/{datetime.now().year:04d}/{datetime.now().month - 1:02d}/{datetime.now().strftime('%B')}.pdf",
            kind=TargetKind.PDF,
        ),
    )
