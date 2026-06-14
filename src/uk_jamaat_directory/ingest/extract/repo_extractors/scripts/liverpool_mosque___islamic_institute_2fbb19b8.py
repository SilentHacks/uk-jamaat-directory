from datetime import datetime
from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    StubbedRenderer,
)


class Extractor(StubbedRenderer):
    key = "liverpool_mosque___islamic_institute_2fbb19b8"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("lmii.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="monthly timetable",
            url="http://lmii.org/monthly",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
