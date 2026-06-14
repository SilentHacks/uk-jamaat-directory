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
    key = "faizan_e_medina_65d28e4f"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("dawateislamimidlands.net",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://dawateislamimidlands.net/prayer-time-table/",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
