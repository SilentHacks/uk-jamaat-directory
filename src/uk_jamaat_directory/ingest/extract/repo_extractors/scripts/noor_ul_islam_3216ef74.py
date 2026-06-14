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
    key = "noor_ul_islam_3216ef74"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("noorulislam.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="monthly-timetable-pdf",
            url="https://noorulislam.org.uk/prayer-timetable-east-london-prayer-times/",
            kind=TargetKind.PDF,
            requires_pdf=True,
        ),
    )
