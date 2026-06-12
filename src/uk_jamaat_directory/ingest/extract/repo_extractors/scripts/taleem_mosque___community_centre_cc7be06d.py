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
    key = "taleem_mosque___community_centre_cc7be06d"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("taleemmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # Verified on homepage, /time-table/, /about-us/, /services/, /services/prayer-facilities/
        # (up to 8 pages, stayed on taleemmosque.com):
        # - No HTML table of multi-day jamaat/iqamah times.
        # - "Timetable" nav links to /time-table/ which advertises "Download 2026 timetable"
        #   pointing at the yearly PDF (Final-Taleem-<YEAR>-salaah-calendar-D2.pdf).
        # - Embedded widget is my-masjid (time.my-masjid.com) — not an allowed embed
        #   domain (only athanplus/masjidal/masjidbox/mawaqit permitted).
        # - Pre-flight suggested HTML; we verified: the authoritative jamaat timetable
        #   is the PDF. Per rules, target the stable HTML landing page that links it,
        #   declare kind=HTML + requires_pdf=True, use StubbedPdfExtractor (stub records
        #   target; still counts as authored, no PDF parsing attempted here).
        # The PDF filename uses the year in the path; we do not hardcode it in the target
        # URL because the landing page is stable and sufficient for the stub.
        self._targets = (
            TargetSpec(
                label="timetable",
                url="https://taleemmosque.com/time-table/",
                kind=TargetKind.HTML,
                requires_pdf=True,
            ),
        )

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets
