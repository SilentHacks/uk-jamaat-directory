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
    key = "markaz_ud_dawat_wal_irshad_islamic_centre_4d8a2fd4"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("plashetgrovemasjid.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    targets = (
        TargetSpec(
            label="timetable",
            url="https://plashetgrovemasjid.org/prayer-timetable/",
            kind=TargetKind.PDF,
            requires_pdf=True,
        ),
    )
