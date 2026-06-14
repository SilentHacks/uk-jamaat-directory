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
    key = "al_madina_jami_masjid_bf325c8e"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("almadina-masjid.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MANUAL)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://almadina-masjid.org.uk/images/almadinatimetable2020.pdf",
            kind=TargetKind.PDF,
            requires_pdf=True,
        ),
    )
