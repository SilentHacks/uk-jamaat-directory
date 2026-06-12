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
    key = "idara_maarif_e_islam_hussainia_mosque_and_community_centre_b89abafc"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("hussainia.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://hussainia.org.uk/wp-content/uploads/2026/03/IMG_5080.jpeg",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
