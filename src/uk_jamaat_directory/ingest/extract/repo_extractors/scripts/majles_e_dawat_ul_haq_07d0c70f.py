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
    key = "majles_e_dawat_ul_haq_07d0c70f"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("majlisedawatulhaq.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # Verified (homepage + /timetable, stayed on majlisedawatulhaq.org.uk, <=8 pages):
        # - Homepage links "/timetable".
        # - /timetable page contains "Download Timetable" link to a monthly PDF
        #   (e.g. June-2026.pdf) and an embedded image preview of the timetable.
        # - No HTML <table> with multi-day jamaat/iqamah times; no allowed embed widgets.
        # - Pre-flight suggested HTML; verification shows the authoritative jamaat timetable
        #   is the PDF (image preview also present). Per rules we target the stable HTML
        #   landing page that links it, declare kind=HTML + requires_pdf=True, and use
        #   StubbedPdfExtractor (stub records the target; counts as authored; no PDF parse).
        # The PDF filename is month-specific; we target the stable landing page so the
        # extractor does not require a monthly script bump just to follow the filename.
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://www.majlisedawatulhaq.org.uk/timetable",
                kind=TargetKind.HTML,
                requires_pdf=True,
            ),
        )
