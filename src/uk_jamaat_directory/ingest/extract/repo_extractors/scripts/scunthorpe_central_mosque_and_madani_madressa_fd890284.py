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
    key = "scunthorpe_central_mosque_and_madani_madressa_fd890284"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("scunthorpemosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    # Verified on http://scunthorpemosque.co.uk/ (stayed within scunthorpemosque.co.uk,
    # visited <=8 pages: /, /Services, /Donations, /pwa-install, /latest.jpg, /latest1.jpg
    # and several 404 probe paths like /prayer-times etc):
    # - Preflight suggested kind=html, but verification shows no HTML <table> of
    #   multi-day jamaat/iqamah times in the DOM on homepage or subpages.
    # - Authoritative "Prayer Timetables" section on homepage (and sidebar card)
    #   links to current "Latest Timetable" as <img src="/latest.jpg?..."> and
    #   previous as /latest1.jpg. These are the published monthly/periodic jamaat
    #   timetables (single-mosque site, not aggregator; no calculated directory).
    # - Embedded iframes are from emasjidlive.co.uk and praydisplay.co.uk (not in
    #   the allowed widget list: athanplus/masjidal/masjidbox/mawaqit only).
    # - External PWA link goes to time.scunthorpemosque.co.uk (different domain).
    # - No dedicated /prayer* /timetable* /salah etc subpages with HTML jamaat data
    #   (all 404 or unrelated content like Services).
    # - Declare the stable latest image asset directly as IMAGE target with
    #   requires_ocr=True using StubbedOcrExtractor (stub records the target;
    #   counts as authored; OCR later will extract the jamaat times from the jpg).
    # - Target the bare /latest.jpg (no year/month in path; the asset is kept
    #   current by the mosque; previous is /latest1.jpg for reference).
    targets = (
        TargetSpec(
            label="timetable",
            url="http://scunthorpemosque.co.uk/latest.jpg",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
