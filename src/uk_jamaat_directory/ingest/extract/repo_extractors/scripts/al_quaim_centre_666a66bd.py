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
    key = "al_quaim_centre_666a66bd"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("alquaim.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)

    @property
    def targets(self):
        now = datetime.now()
        month_names = [
            "Jan",
            "Feb",
            "March",
            "April",
            "May",
            "June",
            "July",
            "Aug",
            "Sept",
            "Oct",
            "Nov",
            "Dec",
        ]
        month_name = month_names[now.month - 1]
        url = f"https://alquaim.co.uk/wp-content/uploads/2021/04/{month_name}-scaled.gif"
        return (
            TargetSpec(
                label="timetable-image",
                url=url,
                kind=TargetKind.IMAGE,
            ),
        )
