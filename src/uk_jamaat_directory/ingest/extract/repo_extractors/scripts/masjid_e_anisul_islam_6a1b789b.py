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
    key = "masjid_e_anisul_islam_6a1b789b"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("anisulislam.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # Verified (start http://anisulislam.com/, stayed on anisulislam.com, <=8 pages):
        # - Homepage nav links "Salah Times" (/salah-times-2/) and has post "Salah Timetable 2026"
        #   (/salah-timetable/) plus "2026 RAMADHAN TIMETABLE"; Masjid > Masjid Downloads lists historical.
        # - /salah-times-2/ and /salah-timetable/ both state "The 2026 Annual Salah Timetable is now
        #   available for download" and link/embed the PDF at
        #   /wp-content/uploads/2025/12/2026-Annual-Salah-Timetable.pdf (no HTML <table> of multi-day
        #   jamaat times; PDF viewer embed only; no allowed athanplus/masjidal/etc widget).
        # - /masjid/masjid-downloads/ lists prior year PDFs (Ramadhan + Annual).
        # - PDF text extract confirms it is the authoritative source and contains explicit JAMAAT
        #   (iqamah) columns: after the start/adhan columns there are dedicated Fajar/Zohar/Asar/
        #   Maghrib/Isha jamaat times (e.g. first rows show jamaat Fajar 7:15 etc., with note
        #   "all Jamaat times are subject to change" and pointer back to the site).
        # - Not an aggregator; not adhan-only. Pre-flight suggested html; verification: the
        #   timetable content is the yearly PDF. Per rules target the stable HTML landing page
        #   that links it, declare kind=HTML + requires_pdf=True, use StubbedPdfExtractor (stub
        #   records the target; counts as authored; no PDF parse here).
        # - The PDF filename is year-specific; we target the stable /salah-times-2/ page so the
        #   extractor does not require a yearly script bump just to follow the filename/path.
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://www.anisulislam.com/salah-times-2/",
                kind=TargetKind.HTML,
                requires_pdf=True,
            ),
        )
