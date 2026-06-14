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
    key = "madrassah_jamiah_farooqiah_79109558"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("jamiahfarooqiah.wixsite.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer_timetable_pdf",
            url="https://c3094682-9ebf-4998-bbb6-d2d557368146.filesusr.com/ugd/0d50ca_b5d627cc0dc34bab96cef831cdf2c3bc.pdf",
            kind=TargetKind.PDF,
        ),
    )
