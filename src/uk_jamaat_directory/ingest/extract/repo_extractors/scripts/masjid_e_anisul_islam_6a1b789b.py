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
    key = "masjid_e_anisul_islam_6a1b789b"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("anisulislam.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="2026 Annual Salah Timetable PDF",
            url="https://www.anisulislam.com/wp-content/uploads/2025/12/2026-Annual-Salah-Timetable.pdf",
            kind=TargetKind.PDF,
        ),
    )
