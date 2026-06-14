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
    key = "salaam_community_centre_and_masjid_8bef1b69"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("salaamca.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # Verified on https://salaamca.org/ (stayed within salaamca.org, visited <=8 pages):
        # - Homepage prominently links "Download Prayer Timetable" to the current-month
        #   PDF under Congregational Prayers heading (https://.../2026/06/june-prayers.pdf).
        # - The PDF is a single-page image-based (scanned graphic) monthly timetable.
        #   No HTML table of multi-day jamaat times; the explicit published timetable
        #   content is this image inside the PDF. No usable text/tables extractable.
        # - Embedded iframe is from prayer.hbksolutions.co.uk (not an allowed widget domain:
        #   only athanplus/masjidal/masjidbox/mawaqit are permitted).
        # - Declare as IMAGE target + requires_ocr=True using StubbedOcrExtractor
        #   (stub records the target; counts as authored; OCR later).
        # - The PDF filename is month-specific (/<year>/<mm>/<month>-prayers.pdf); build
        #   the URL from current date in __init__ (no hardcoded year/month).
        now = datetime.now()
        y = now.year
        m = now.strftime("%m")
        mon = now.strftime("%B").lower()
        pdf_url = f"https://salaamca.org/wp-content/uploads/{y}/{m}/{mon}-prayers.pdf"
        self.targets = (
            TargetSpec(
                label="timetable",
                url=pdf_url,
                kind=TargetKind.IMAGE,
                requires_ocr=True,
            ),
        )
