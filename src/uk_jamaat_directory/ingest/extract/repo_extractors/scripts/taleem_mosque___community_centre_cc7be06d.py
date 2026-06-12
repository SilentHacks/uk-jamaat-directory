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
    key = "taleem_mosque___community_centre_cc7be06d"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("taleemmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        self._targets = (
            TargetSpec(
                label="timetable",
                url="https://taleemmosque.com/time-table/",
                kind=TargetKind.HTML,
                requires_pdf=True,
            ),
        )

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets
