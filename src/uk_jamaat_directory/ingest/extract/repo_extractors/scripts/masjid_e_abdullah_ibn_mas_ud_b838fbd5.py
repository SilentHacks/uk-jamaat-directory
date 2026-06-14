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
    key = "masjid_e_abdullah_ibn_mas_ud_b838fbd5"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("abdullahibnmasud.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable_pdf",
            url="https://abdullahibnmasud.co.uk/timetable",
            kind=TargetKind.PDF,
        ),
    )
