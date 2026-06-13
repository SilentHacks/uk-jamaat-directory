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
    key = "masjid_adam_272282bb"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("oadbych.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="monthly_salah_timetable",
            url="https://oadbych.org/wp-content/uploads/2026/05/Masjid-Adam-Salaat-Timetable-June-2026-v1.1.pdf",
            kind=TargetKind.PDF,
        ),
    )
