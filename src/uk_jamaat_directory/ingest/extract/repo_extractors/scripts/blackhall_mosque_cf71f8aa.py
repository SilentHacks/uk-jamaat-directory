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
    """Blackhall Mosque — masjidbox widget (REDUX_STATE iqamah/jamaat times)."""

    key = "blackhall_mosque_cf71f8aa"
    version = "2026.06.18.1"
    source_match = SourceMatch(domains=("blackhallmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/blackhall-mosque-1715251717791",
            kind=TargetKind.HTML,
        ),
    )
