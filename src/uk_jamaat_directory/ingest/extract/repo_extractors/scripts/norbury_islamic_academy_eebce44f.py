from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import Table, extract_tables
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
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    _TabularTimetableMixin,
)


class Extractor(_TabularTimetableMixin, BaseMosqueWebsiteExtractor):
    key = "norbury_islamic_academy_eebce44f"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("norbury.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://norbury.org/?page=salaah_times&show=month",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date",)
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 4,
        Prayer.DHUHR: 7,
        Prayer.ASR: 9,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        tables = extract_tables(artifact.text())
        if not tables:
            return ExtractorResult(
                rows=[], no_schedule_reason="timetable table not found"
            )
        table = tables[0]
        # Skip prayer header row and use column header row
        rows_to_process = table.rows[1:] if len(table.rows) > 1 else table.rows
        adjusted_table = Table(rows_to_process)
        return self._extract_from_table(ctx, adjusted_table)
