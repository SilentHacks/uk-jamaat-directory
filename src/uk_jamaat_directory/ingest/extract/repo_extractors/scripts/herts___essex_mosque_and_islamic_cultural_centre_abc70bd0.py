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
    key = "herts___essex_mosque_and_islamic_cultural_centre_abc70bd0"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("hertsandessexmosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    # Verified on https://hertsandessexmosque.co.uk/ and /timetable (stayed within
    # hertsandessexmosque.co.uk, visited <=8 pages; also checked /ramadan):
    # - No HTML table of multi-day jamaat/iqamah times present in the DOM.
    # - Authoritative current-month timetable is an embedded PNG image on /timetable
    #   (heading "June 2026 - Current Month" + large <img> of timetable).
    # - "Download Full Annual Calendar" button links to yearly PDF.
    # - Homepage "Timetable" card links to the same image content.
    # - No allowed embedded widgets (athanplus/masjidal/masjidbox/mawaqit).
    # - Page text explicitly refers to "Jama'at prayer times" and mosque opening
    #   relative to them, and lists two Jummah jamaat times (13:15 / 14:00).
    # - Pre-flight suggested HTML; verification confirms image-based timetable on
    #   the HTML page, so declare kind=HTML + requires_ocr=True and use
    #   StubbedOcrExtractor. The stub records the target (counts as authored);
    #   no OCR performed here.
    # Target the stable /timetable landing page (no month-specific URL needed;
    # the page always carries the current month's image).
    targets = (
        TargetSpec(
            label="timetable",
            url="https://hertsandessexmosque.co.uk/timetable",
            kind=TargetKind.HTML,
            requires_ocr=True,
        ),
    )
