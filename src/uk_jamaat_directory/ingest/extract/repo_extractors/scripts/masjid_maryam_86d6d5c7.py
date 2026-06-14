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
    key = "masjid_maryam_86d6d5c7"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("masjidmaryam.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="prayer_timetable_image",
            url="https://masjidmaryam.co.uk/prayer-times",
            kind=TargetKind.IMAGE,
        ),
    )
