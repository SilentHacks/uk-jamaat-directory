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
    key = "islamic_dawah_centre_503c0e03"
    version = "2026.06.12.3"
    source_match = SourceMatch(domains=("idcuk.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # Verified on http://idcuk.org/ and https://idcuk.org/demo/prayer-times/
        # (stayed within idcuk.org, <=8 pages; also checked /ramadan-calendar/):
        # - No HTML table of multi-day jamaat/iqamah times.
        # - Authoritative timetable is a yearly PDF linked from /prayer-times/
        #   (https://idcuk.org/demo/wp-content/uploads/2026/03/idc-pt-2026.pdf) plus
        #   monthly PNG images (e.g. idcmay26.png) embedded on the page for the
        #   current month visual. The PDF exceeds fetch size limits (6MB > 5MB) in
        #   the smoke-test fetcher, so rows cannot be produced here.
        # - No allowed widgets.
        # - Target the stable HTML landing page; declare requires_ocr=True because
        #   the visible timetable content is image-based. Use StubbedOcrExtractor so
        #   the source is recorded; the canonical "image target — awaiting OCR"
        #   reason is accepted for empty results.
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://idcuk.org/demo/prayer-times/",
                kind=TargetKind.HTML,
                requires_ocr=True,
            ),
        )
