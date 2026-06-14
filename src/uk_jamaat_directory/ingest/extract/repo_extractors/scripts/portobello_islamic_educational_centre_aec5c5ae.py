from uk_jamaat_directory.domain import Prayer
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
    key = "portobello_islamic_educational_centre_aec5c5ae"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("portobellomosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://portobellomosque.org/prayer-timetable/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
