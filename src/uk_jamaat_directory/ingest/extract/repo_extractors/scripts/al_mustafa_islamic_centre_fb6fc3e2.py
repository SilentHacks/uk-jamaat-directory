from datetime import datetime
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy, RunFrequency, SourceMatch, TargetKind, TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    StubbedPdfExtractor,
)


class Extractor(StubbedPdfExtractor):
    key = "al_mustafa_islamic_centre_fb6fc3e2"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("islamiccentre.ie",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="ramadan-timetable",
            url=f"http://www.islamiccentre.ie/wp-content/uploads/Ramadan-Timetable-{datetime.now().year}.pdf",
            kind=TargetKind.PDF,
        ),
    )
