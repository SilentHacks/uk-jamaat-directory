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
    key = "leeds_grand_mosque_2b2a8539"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("leedsgrandmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # Verified (start https://leedsgrandmosque.com/, stayed on leedsgrandmosque.com,
        # visited <=8 pages: /, /services/friday-prayer, /prayer, /services/ramadan,
        # and probe paths /prayer-times /prayer /salah /salat /namaz /timetable /time-table
        # /schedule /jumuah /jumma /calendar /mosque-times — most 404 or non-timetable):
        # - Homepage renders explicit JAMAAT ("jammah") times inline for today:
        #   fajr adhan 03:17 jammah 04:00; dhuhr 13:06/13:30; asr 17:34/18:30;
        #   maghrib 21:40/21:45; isha "Combined with Maghrib". Also "Friday Prayers (Jumu’ah)
        #   start at 13:00".
        # - Prominent "download timetable" link points to /uploads/files/A3_calendar2026_v2_(1).pdf
        #   (confirmed 200 application/pdf; this is the yearly A3 calendar containing the
        #   authoritative multi-month jamaat times).
        # - No HTML <table> with multi-day (monthly/yearly) jamaat data on homepage or probed
        #   subpages. The visible prayers-list is today-only (not the broadest timetable).
        # - No embedded timetable widgets from allowed domains
        #   (athanplus/masjidal/masjidbox/mawaqit).
        # - Not an aggregator/directory site (single-mosque content and branding); has jamaat
        #   times (inline + PDF), not adhan-only.
        # - Preflight predicted html; verification: the durable timetable content is the PDF.
        #   Target the stable homepage (always links the current calendar) as kind=HTML with
        #   requires_pdf=True and use StubbedPdfExtractor (stub records the target for the
        #   source; counts as authored; no PDF parsing in this script). This avoids embedding
        #   a year-specific or versioned filename in the extractor and matches the pattern for
        #   other sites with year-named PDF calendars linked from a stable landing page.
        # - Direct PDF asset URL contains a calendar year and uploader suffix; using the
        #   homepage keeps the script stable across annual updates.
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://leedsgrandmosque.com/",
                kind=TargetKind.HTML,
                requires_pdf=True,
            ),
        )
