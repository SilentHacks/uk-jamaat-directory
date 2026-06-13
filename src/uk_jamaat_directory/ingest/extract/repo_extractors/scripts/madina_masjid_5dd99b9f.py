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


def _get_month_url() -> str:
    """Return the current month PDF URL."""
    months = [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    ]
    month = months[datetime.now().month - 1]
    return f"http://darwenmosque.co.uk/downloads/{month}.pdf"


class Extractor(StubbedPdfExtractor):
    key = "madina_masjid_5dd99b9f"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("darwenmosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="monthly_timetable",
            url=_get_month_url(),
            kind=TargetKind.PDF,
        ),
    )
