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
    key = "old_kent_road_mosque___islamic_cultural_centre_586f4672"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("manuk.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # The /prayers page links a 27 MB PDF timetable with Fajr/Zuhr/Asr/
        # Maghrib/Isha jamaat (Jamā'ah) columns. The PDF exceeds the 5 MB
        # fetch limit, so we target the landing page with requires_pdf=True
        # to record the source for future PDF parsing.
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://www.manuk.org/prayers",
                kind=TargetKind.HTML,
                requires_pdf=True,
            ),
        )
