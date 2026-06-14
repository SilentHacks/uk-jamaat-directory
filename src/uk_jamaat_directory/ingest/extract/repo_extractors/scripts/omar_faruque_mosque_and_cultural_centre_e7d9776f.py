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
    key = "omar_faruque_mosque_and_cultural_centre_e7d9776f"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("omarfaruquemosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="2026 Prayer Timetable (PDF)",
            url=f"http://www.omarfaruquemosque.org.uk/salahtimes/CAMBRIDGE_PRAYER_TIMES_{datetime.now().year}.pdf",
            kind=TargetKind.PDF,
        ),
    )
