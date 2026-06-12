from datetime import datetime

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
    key = "masjid_e_umar_bee1d467"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("masjid-e-umar.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # Verified: no HTML table with jamaat (iqamah) times on the site.
        # /prayer-times serves an iframe to an external widget (go2masjid.com
        # — not in the allowed embedded list: athanplus/masjidal/masjidbox/mawaqit)
        # plus a stale month image. The mosque publishes its authoritative
        # monthly timetable (with jamaat times) as a JPEG on the allowed domain,
        # linked from the homepage (e.g. "Download JUNE 2026 prayer times" ->
        # /wordpress/wp-content/uploads/2026/05/JUNE-2026.jpeg). Jumuah times
        # are also announced in text on the homepage. Declare the homepage as
        # the IMAGE target (stubbed; OCR later). Never leave the source domain.
        # The homepage carries the reference to the current timetable image.
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://masjid-e-umar.co.uk/",
                kind=TargetKind.IMAGE,
                requires_ocr=True,
            ),
        )
