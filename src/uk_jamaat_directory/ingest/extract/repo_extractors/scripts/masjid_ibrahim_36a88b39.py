from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    MasjidboxReduxExtractor,
)


class Extractor(MasjidboxReduxExtractor):
    """UKIM Masjid Ibrahim — masjidbox widget (REDUX_STATE iqamah/jamaat times)."""

    key = "masjid_ibrahim_36a88b39"
    version = "2026.06.18.1"
    source_match = SourceMatch(domains=("masjidibrahim.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/ukim-masjid-ibrahim",
            kind=TargetKind.HTML,
        ),
    )
