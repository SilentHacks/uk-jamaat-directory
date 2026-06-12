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
    key = "al_jamia_suffa_tul_islam_grand_mosque_9b196325"
    version = "2026.06.12.5"
    source_match = SourceMatch(domains=("bradfordgrandmosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    targets = (
        TargetSpec(
            label="home",
            url="https://bradfordgrandmosque.co.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        # Homepage (and other site pages) contain no jamaat timetable table.
        # The only schedule is a large image-based yearly PDF calendar linked
        # from the nav (CALENDAR). The PDF exceeds fetch size limits and has
        # no text layer for extraction. Use the allowed empty reason so this
        # PDF-only source can be tracked for future PDF/image parser support.
        # Never invent rows; no HTML jamaat times are present.
        return ExtractorResult(rows=[], no_schedule_reason="pdf target — awaiting parser")
