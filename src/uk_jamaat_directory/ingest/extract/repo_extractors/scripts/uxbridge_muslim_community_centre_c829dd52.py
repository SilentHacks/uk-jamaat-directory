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
    key = "uxbridge_muslim_community_centre_c829dd52"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("uxbridgemasjid.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        m = now.strftime("%B")
        y = now.year
        # The site publishes monthly image timetables under /assets/ with names
        # like May2026.jpg or June2026v2.jpg (v2 for some months).
        if m == "June":
            url = f"https://www.uxbridgemasjid.org.uk/assets/{m}{y}v2.jpg"
        else:
            url = f"https://www.uxbridgemasjid.org.uk/assets/{m}{y}.jpg"
        self._targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.IMAGE,
                requires_ocr=True,
            ),
        )

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets
