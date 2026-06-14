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
    key = "masjid_ul_asqa_and_islamic_centre_174c4655"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("masjidulaqsa.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer-timetable",
            url="https://masjidulaqsa.org.uk/_files/ugd/59a702_39c8827996ce431ca60d5d18f358c7ed.pdf",
            kind=TargetKind.PDF,
        ),
    )
