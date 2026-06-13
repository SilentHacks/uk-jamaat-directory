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
    key = "croydon_mosque___islamic_centre_ea033744"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("croydonmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="monthly_timetable",
            url="http://croydonmosque.com/pdf/cmic_timetable_march_april_2026.pdf",
            kind=TargetKind.PDF,
        ),
    )
