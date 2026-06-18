from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    MawaqitConfDataExtractor,
)


class Extractor(MawaqitConfDataExtractor):
    """Madina Masjid Sheffield — mawaqit.net (confData iqamaCalendar jamaat times).

    Previously stubbed (returned no rows) on the assumption the page required
    JS rendering; the schedule is in the static ``confData`` JSON.
    """

    key = "medina_mosque_4d5c8a78"
    version = "2026.06.18.1"
    source_match = SourceMatch(domains=("madinamasjid.org.uk", "mawaqit.net"))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://mawaqit.net/en/madina-masjid-sheffield-sheffield-s8-0zu-united-kingdom",
            kind=TargetKind.HTML,
        ),
    )
