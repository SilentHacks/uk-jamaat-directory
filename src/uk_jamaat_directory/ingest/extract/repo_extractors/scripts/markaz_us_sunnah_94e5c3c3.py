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
    key = "markaz_us_sunnah_94e5c3c3"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("musunnah.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://musunnah.com/prayer-timetable/",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
