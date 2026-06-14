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
    key = "brentwood_mosque_6c9f1e29"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("free-4413453.webador.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # The site publishes the authoritative monthly timetable as an image
        # (e.g. june-2026-timetable-a4-page-001-1-high.jpg) embedded directly
        # on the homepage. No HTML table, no text jamaat columns, and no
        # 3rd-party widget present in the DOM. The images contain the jamaat
        # (iqamah) times. Declare the homepage (on the allowed domain) as the
        # IMAGE target (stubbed; OCR later). Never leave the source domain.
        # The homepage always carries the current timetable image(s).
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://free-4413453.webador.co.uk/",
                kind=TargetKind.IMAGE,
                requires_ocr=True,
            ),
        )
