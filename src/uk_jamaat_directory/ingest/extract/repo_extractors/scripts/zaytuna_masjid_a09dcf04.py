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
    key = "zaytuna_masjid_a09dcf04"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("abrahamicfoundation.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="monthly_salah_timetable",
            url="https://legacy.abrahamicfoundation.org.uk/wp-content/uploads/2024/08/05-May-Salah-Timetable-Zaytuna.pdf",
            kind=TargetKind.PDF,
        ),
    )
