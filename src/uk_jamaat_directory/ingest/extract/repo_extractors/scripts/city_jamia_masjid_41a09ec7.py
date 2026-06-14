from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    StubbedOcrExtractor,
)


class Extractor(StubbedOcrExtractor):
    key = "city_jamia_masjid_41a09ec7"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("islamicacademy.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="monthly_timetable",
            url="https://islamicacademy.co.uk/june-2026-prayer-timetable/",
            kind=TargetKind.IMAGE,
        ),
    )
