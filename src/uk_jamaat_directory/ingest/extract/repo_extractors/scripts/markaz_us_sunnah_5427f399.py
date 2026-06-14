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
    key = "markaz_us_sunnah_5427f399"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("musunnah.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # Verified (stayed on musunnah.com, <=8 pages):
        # - / (homepage) has nav link "Prayer Times" -> /prayer-timetable/
        # - /prayer-timetable/ (and /prayer-timetable) serves "June 2026 Prayer Times"
        #   as an embedded JPEG image (WhatsApp-Image-...jpeg) + download link to the
        #   same image file on the same domain. No <table> with date/fajr/jamaat columns.
        # - No HTML multi-day jamaat timetable present.
        # - No allowed embedded widgets (athanplus/masjidal/masjidbox/mawaqit).
        # - Not an aggregator; single-mosque site. Timetable image is the authoritative
        #   monthly schedule (convention: treat as jamaat source for OCR later).
        # Declare the stable page URL as IMAGE target (requires_ocr) so the source
        # is recorded and the fetcher captures the current image artifact.
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://musunnah.com/prayer-timetable/",
                kind=TargetKind.IMAGE,
                requires_ocr=True,
            ),
        )
