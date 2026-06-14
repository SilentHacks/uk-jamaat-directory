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
    key = "the_eccles_and_salford_islamic_society_9c0cfd89"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("ecclesmosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer timetable",
            url="https://docs.google.com/uc?id=1XrntX9YOCfh17ItCvXud97-tmTcZRapB&export=download",
            kind=TargetKind.PDF,
        ),
    )
