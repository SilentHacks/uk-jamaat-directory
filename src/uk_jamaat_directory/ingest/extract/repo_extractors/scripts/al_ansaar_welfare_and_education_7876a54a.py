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
    key = "al_ansaar_welfare_and_education_7876a54a"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("alansaar.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://alansaar.org.uk/wp-content/uploads/2019/03/Prayer-timetable-widget.png",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
