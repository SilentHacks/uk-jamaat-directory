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
    key = "portsmouth_jami_mosque_7e4aac38"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("portsmouthjamimosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://portsmouthjamimosque.org/wp-content/uploads/2023/10/Portsmouth-Jami-Mosque-and-Islamic-Centre-Masjid-Salah-Timings-1.pdf",
            kind=TargetKind.PDF,
            requires_pdf=True,
        ),
    )
