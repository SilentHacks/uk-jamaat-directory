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
    key = "camberley_mosque_40ad85cc"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("camberleymosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://camberleymosque.org.uk/images/stories/msj-2026-cal.pdf",
            kind=TargetKind.PDF,
            requires_pdf=True,
        ),
    )
