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
    """Masjid Khadijah — masjidbox widget (REDUX_STATE iqamah/jamaat times).

    The previous version parsed JSON-LD ``startDate`` values, which are prayer
    *start* (adhan) times, not the congregation times. masjidbox exposes the
    jamaat times via ``REDUX_STATE`` ``iqamah``.
    """

    key = "masjid_khadijah_and_islamic_centre_1e1c5e1e"
    version = "2026.06.18.1"
    target_label = "masjidbox_timetable"
    source_match = SourceMatch(domains=("ukimpeterborough.org.uk", "masjidbox.com"))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="masjidbox_timetable",
            url="https://masjidbox.com/prayer-times/khadijah",
            kind=TargetKind.HTML,
        ),
    )
