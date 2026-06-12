from __future__ import annotations

from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
    ExtractContext,
    ExtractorResult,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "ashrafia_mosque_8a730137"
    version = "2026.06.12.5"
    source_match = SourceMatch(domains=("ashrafiamasjid.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        self._targets = (
            TargetSpec(
                label="timetable",
                url="https://ashrafiamasjid.org/",
                kind=TargetKind.HTML,
            ),
        )

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        # The jamaat timetable is published only as a large yearly PDF linked from
        # the homepage. No inline multi-day jamaat table exists in the HTML.
        # Smoke test cannot fetch the PDF (exceeds artifact size limit), so we
        # record the target and return the canonical "awaiting parser" reason.
        return ExtractorResult(rows=[], no_schedule_reason="pdf target — awaiting parser")
