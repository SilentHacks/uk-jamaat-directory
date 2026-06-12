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
    key = "jame_masjid_e_noor_95e16e98"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("masjidenoor.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidenoor.com/wp-content/uploads/2025/12/Masjid-e-Noor-Calendar-2026-Website_compressed.pdf",
            kind=TargetKind.PDF,
            requires_pdf=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        return ExtractorResult(rows=[], no_schedule_reason="image target — awaiting OCR")
