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
    key = "al_jamat_ul_muslimin_of_bangladesh_721af4e2"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("aljamaat.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://aljamaat.co.uk/documents/timetable/875a529c3313224c56e15d1a2401dd19.png",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
