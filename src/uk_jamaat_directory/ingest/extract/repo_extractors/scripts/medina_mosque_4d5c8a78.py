from uk_jamaat_directory.domain import Prayer
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
    TableTimetableExtractor,
)


class Extractor(TableTimetableExtractor):
    key = "medina_mosque_4d5c8a78"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("madinamasjid.org.uk", "mawaqit.net"))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://mawaqit.net/en/madina-masjid-sheffield-sheffield-s8-0zu-united-kingdom",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("fajr", "dhuhr", "asr", "maghrib", "isha")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "dhuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """JS-rendered targets require browser rendering not available in sandbox."""
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        # JS-rendered content can't be processed in static sandbox
        return ExtractorResult(
            rows=[],
            no_schedule_reason="pdf target — awaiting parser"
        )
