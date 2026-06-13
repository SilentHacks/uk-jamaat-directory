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
    key = "crawley_mosque_51492ddd"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("crawleymosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="monthly_prayer_timetable",
            url="http://crawleymosque.com/wp-content/uploads/2026/06/Crawley-Masjid-Prayer-Timetable-June-2026.pdf",
            kind=TargetKind.PDF,
            requires_pdf=True,
        ),
    )
