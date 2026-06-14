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
    key = "banbury_makkah_masjid_f31a025e"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("banburymadnimasjid.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="makkah_timetable",
            url=f"https://banburymadnimasjid.com/assets/pdf/makkah-time-table-{datetime.now().strftime('%B-%Y').lower()}.pdf",
            kind=TargetKind.PDF,
        ),
    )
