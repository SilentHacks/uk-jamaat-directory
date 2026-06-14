from datetime import datetime

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
    key = "markazi_jamia_masjid_bilal_1d207fd5"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("bilalmasjid.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="annual timetable",
            url=f"https://bilalmasjid.org.uk/salaah-timetable-{datetime.now().year}/",
            kind=TargetKind.PDF,
        ),
    )
