from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
    ExtractContext,
    ExtractorResult,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "al_madina_jami_masjid_bf325c8e"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("almadina-masjid.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # Verification (stayed on almadina-masjid.org.uk; <=8 pages: /, /prayer-timetable.html,
        # /downloads.html, and 404s for /prayer, /salah, /timetable, /jumuah, /calendar):
        # - Homepage links to /prayer-timetable.html and a Ramadan-specific PDF.
        # - /prayer-timetable.html contains a direct link to the authoritative PDF:
        #   /images/almadinatimetable2020.pdf (serves application/pdf; contains the mosque's
        #   prayer timetable image/PDF with jamaat times).
        # - No HTML timetable table or jamaat columns found in static HTML on the site.
        # - No embedded widgets from allowed providers (athanplus/masjidal/masjidbox/mawaqit).
        # - Site is single-mosque (not aggregator/directory). Has jamaat times (via PDF), not adhan-only.
        # - Pre-flight suggested html; verified: PDF (image-based timetable inside PDF).
        # The PDF contains only an embedded image of the timetable (no extractable text/tables).
        # Per rules, PDF/image targets without parsable jamaat text use the canonical awaiting reason.
        # Broadest available: the main (non-Ramadan) timetable PDF.
        # URL is site-provided and stable (legacy "2020" in filename; no year computation needed).
        url = "https://almadina-masjid.org.uk/images/almadinatimetable2020.pdf"
        self.targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        # PDF is image-only (no text, no tables via pdf helpers). Cannot extract jamaat rows
        # without OCR (out of scope for repo extractors). Record target and use canonical reason.
        return ExtractorResult(rows=[], no_schedule_reason="pdf target — awaiting parser")
