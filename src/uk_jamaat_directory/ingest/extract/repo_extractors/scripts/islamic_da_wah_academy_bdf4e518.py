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
    key = "islamic_da_wah_academy_bdf4e518"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("idauk.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="timetable_pdf",
            url=f"https://idauk.org/pdf/IDA_jun{datetime.now().strftime('%y')}.pdf",
            kind=TargetKind.PDF,
        ),
    )
