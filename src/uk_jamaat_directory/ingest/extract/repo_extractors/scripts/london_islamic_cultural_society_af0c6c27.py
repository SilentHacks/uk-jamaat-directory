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
    key = "london_islamic_cultural_society_af0c6c27"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("lics.info",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    # Verified on https://www.lics.info/ (stayed within lics.info, visited <=8 pages:
    # /, /prayer-time, /schedule, /ramadan, /events, /guide and probe paths).
    # - Preflight suggested kind=html. Verification: homepage and /prayer-time
    #   are Wix sites with no static or rendered HTML <table> containing multi-day
    #   jamaat/iqamah times. No adhan+jamaat columns or "jamaat = adhan + N min"
    #   rule text extractable from HTML/JSON.
    # - /ramadan page contains the explicit "Timetable 2026" / "Jamaat times"
    #   section with an embedded GIF image that is the published monthly/seasonal
    #   timetable showing jamaat (iqamah/congregation) times. Text on page:
    #   "Please see below Ramadan time table for more information on Jamaat times".
    # - No allowed embedded widgets (athanplus/masjidal/masjidbox/mawaqit).
    #   No PDF/JSON feed of the timetable.
    # - Single-mosque site (not aggregator/directory of many mosques).
    # - Declare the stable /ramadan page (host of the authoritative jamaat timetable
    #   graphic) as IMAGE target with requires_ocr=True using StubbedOcrExtractor
    #   (stub records the target; counts as authored; OCR later extracts jamaat).
    # - This is the broadest timetable found (monthly/seasonal with jamaat).
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.lics.info/ramadan",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
