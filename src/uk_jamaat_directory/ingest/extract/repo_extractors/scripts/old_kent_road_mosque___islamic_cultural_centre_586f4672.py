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
        # The /prayers page links the published Prayer Timetable PDF. No HTML table
        # of jamaat times is present on the site (Wix-rendered; static fetch shows
        # no <table> and no allowed timetable widgets). The timetable lives in the
        # linked PDF (requires_pdf) but the PDF exceeds fetch byte limits and PDF
        # parsing is out of scope, so we target the small landing page and stub.
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://www.manuk.org/prayers",
                kind=TargetKind.HTML,
                requires_pdf=True,
            ),
        )
