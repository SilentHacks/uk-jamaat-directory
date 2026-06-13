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
    key = "masjid_e_salaam_9b70fb05"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("masjidesalaam.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="salah_timetable",
            url="http://masjidesalaam.com/phocadownloadpap/MSA_SALAAT TIMES 2025_Issue1.pdf",
            kind=TargetKind.PDF,
        ),
    )
    requires_pdf = True
