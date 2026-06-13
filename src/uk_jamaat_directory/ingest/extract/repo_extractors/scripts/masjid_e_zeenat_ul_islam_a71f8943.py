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
    key = "masjid_e_zeenat_ul_islam_a71f8943"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("masjidzeenatulislam.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # Verified (start https://masjidzeenatulislam.org.uk/, stayed on
        # masjidzeenatulislam.org.uk, visited <=8 pages: /, /timetable/, /contact/,
        # and probe paths /prayer-times /prayer /salah /salat /namaz /timetable
        # /time-table /schedule /jumuah /jumma /calendar /mosque-times):
        # - Homepage has a today-only "Jamaat Times" widget (plugin-rendered;
        #   explicit jamaat/iqamah values, plus Jumu'ah times; not adhan-only).
        # - /timetable/ is the stable landing page with links to the current
        #   bi-monthly PDF (e.g. Bi-Monthly_TimeTable_...May_Jun_2026.pdf) and
        #   embedded JPEG previews of the pages. No <table> with multi-day
        #   jamaat schedule on any HTML page.
        # - No allowed embedded widgets (athanplus etc.).
        # - Not an aggregator; single-mosque site with jamaat times in the PDF.
        # - Preflight suggested html; verification: the broadest durable
        #   timetable is the bi-monthly PDF. Target the stable /timetable/
        #   landing page (always links the latest PDF) as kind=HTML with
        #   requires_pdf=True and use StubbedPdfExtractor (stub records the
        #   target; counts as authored; no PDF parse in script).
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://masjidzeenatulislam.org.uk/timetable/",
                kind=TargetKind.HTML,
                requires_pdf=True,
            ),
        )
