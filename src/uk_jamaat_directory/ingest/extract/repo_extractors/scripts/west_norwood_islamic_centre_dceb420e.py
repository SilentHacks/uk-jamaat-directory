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
    """West Norwood Islamic Centre — masjidbox widget (REDUX_STATE iqamah times)."""

    key = "west_norwood_islamic_centre_dceb420e"
    version = "2026.06.18.1"
    source_match = SourceMatch(domains=("westnorwoodmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/west-norwood-mosque",
            kind=TargetKind.HTML,
        ),
    )
