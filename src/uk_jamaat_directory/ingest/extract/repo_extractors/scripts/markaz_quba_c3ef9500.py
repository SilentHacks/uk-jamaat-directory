from datetime import datetime

from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    StubbedOcrExtractor,
)


class Extractor(StubbedOcrExtractor):
    key = "markaz_quba_c3ef9500"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("markazquba.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    @property
    def targets(self):
        year = datetime.now().year
        month = datetime.now().month
        month_name = datetime.now().strftime("%B").lower()

        return (
            TargetSpec(
                label=f"monthly_timetable_{month_name}_{year}",
                url=f"http://markazquba.org.uk/salat-time-table/",
                kind=TargetKind.IMAGE,
            ),
        )
