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
    """Madani Institute Preston — masjidbox widget (REDUX_STATE iqamah/jamaat times).

    Previously scraped the rendered widget DOM for [label, adhan, iqamah]
    pairs, which was fragile; the iqamah (jamaat) times are available
    deterministically in ``REDUX_STATE``.
    """

    key = "madani_institute_preston_3318d3e0"
    version = "2026.06.18.1"
    source_match = SourceMatch(domains=("mamissionuk.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/ma-mission-learning-centre",
            kind=TargetKind.HTML,
        ),
    )
