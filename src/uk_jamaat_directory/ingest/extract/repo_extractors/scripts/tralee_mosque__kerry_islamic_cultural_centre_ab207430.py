"""
Tralee Mosque (Kerry Islamic Cultural Centre) extractor.

Prayer timetable is on the homepage in a table showing adhan and jamaat times.
The table is populated dynamically via JavaScript which fetches the month's PDF
and updates links. The timetable is rendered on page load.
"""

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
    key = "tralee_mosque__kerry_islamic_cultural_centre_ab207430"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("traleemasjidkicc.ie",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="salah_times_with_jamaat",
            url="https://traleemasjidkicc.ie/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
