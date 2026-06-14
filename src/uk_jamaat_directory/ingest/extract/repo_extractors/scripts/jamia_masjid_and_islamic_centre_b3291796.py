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
    key = "jamia_masjid_and_islamic_centre_b3291796"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("jamiamasjid-southall.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer timetable",
            url="http://jamiamasjid-southall.org.uk/Timetable/2026_May_Jun_Timetable_JMS.pdf",
            kind=TargetKind.PDF,
        ),
    )
