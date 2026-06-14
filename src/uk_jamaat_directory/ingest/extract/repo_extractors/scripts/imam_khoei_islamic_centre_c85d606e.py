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
    key = "imam_khoei_islamic_centre_c85d606e"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("al-khoei.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer_timetable",
            url="https://www.al-khoei.org/prayer_timetable.pdf",
            kind=TargetKind.PDF,
        ),
    )
