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
    key = "masjid_at_taqwa_islamic_education_centre_574e0f4d"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("attaqwa.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)

    @property
    def targets(self):
        month = datetime.now().month
        year = datetime.now().year
        month_names = [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ]
        month_name = month_names[month - 1]
        return (
            TargetSpec(
                label=f"timetable_{month_name}_{year}",
                url=f"https://attaqwa.co.uk/timetables/At-Taqwa-{month_name}.pdf",
                kind=TargetKind.PDF,
            ),
        )
