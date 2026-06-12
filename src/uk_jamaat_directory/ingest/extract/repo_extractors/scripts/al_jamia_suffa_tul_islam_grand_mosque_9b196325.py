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
    key = "al_jamia_suffa_tul_islam_grand_mosque_9b196325"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("bradfordgrandmosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # Verified (start http://bradfordgrandmosque.co.uk/, stayed on
        # bradfordgrandmosque.co.uk, visited <=8 pages: /, /services,
        # /gallery, /videos, /contribute, /visits-and-tours, /contact,
        # and probe paths /prayer-times /prayer /salah /salat /namaz
        # /timetable /time-table /schedule /jumuah /jumma /calendar
        # /mosque-times — all 404 or non-timetable):
        # - Homepage has no inline prayer/jamaat timetable.
        # - No embedded timetable widgets from allowed domains
        #   (athanplus/masjidal/masjidbox/mawaqit).
        # - The "CALENDAR" nav link points to
        #   assets/Calendar.pdf?year=2026 (confirmed 200,
        #   5.7 MB application/pdf, 13 pages, all image-based —
        #   zero extractable text).
        # - Not an aggregator/directory site (single-mosque content
        #   and branding); has jamaat times in the PDF calendar,
        #   not adhan-only.
        # - Preflight predicted html; verification: the durable
        #   timetable content is the image-based PDF calendar.
        #   Target the stable homepage (always links the current
        #   calendar) as kind=HTML with requires_pdf=True and use
        #   StubbedPdfExtractor (stub records the target for the
        #   source; counts as authored; no PDF parsing in this
        #   script). This avoids embedding a year-specific query
        #   parameter in the extractor and matches the pattern for
        #   other sites with year-named PDF calendars linked from
        #   a stable landing page.
        self.targets = (
            TargetSpec(
                label="timetable",
                url="http://bradfordgrandmosque.co.uk/",
                kind=TargetKind.HTML,
                requires_pdf=True,
            ),
        )
