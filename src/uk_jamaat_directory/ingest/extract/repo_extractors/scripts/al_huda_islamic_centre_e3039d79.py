from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorResult,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    BaseMosqueWebsiteExtractor,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "al_huda_islamic_centre_e3039d79"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("alhudamasjid.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://alhudamasjid.org.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="artifact was empty",
            )

        html = artifact.text().lower()

        # Check if site is a directory/aggregator
        if "time.now" in html or "calculated" in html or "calculator" in html:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="aggregator listing",
            )

        return ExtractorResult(
            rows=[],
            no_schedule_reason="no jamaat times found",
        )
