"""
Markfield Mosque prayer timetable extractor.

Source: https://islamic-foundation.org.uk/projects/markfield-mosque
Target: Monthly PDF timetable
"""
from datetime import datetime

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
    key = "the_markfield_mosque_21235fbd"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("islamic-foundation.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    
    targets = (
        TargetSpec(
            label="prayer_timetable_pdf",
            url="https://islamic-foundation.org.uk/projects/markfield-mosque",
            kind=TargetKind.PDF,
        ),
    )
