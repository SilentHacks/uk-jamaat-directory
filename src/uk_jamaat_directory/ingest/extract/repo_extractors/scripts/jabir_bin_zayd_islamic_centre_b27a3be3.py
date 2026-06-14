from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorResult,
    ExtractorWarning,
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
    key = "jabir_bin_zayd_islamic_centre_b27a3be3"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("ahlulistiqamah.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://ahlulistiqamah.co.uk/index.php/en/monthly-prayer-times-auto-upload",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr iqama",
        Prayer.DHUHR: "dhuhr iqama",
        Prayer.ASR: "asr iqama",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha iqama",
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        # The page has a title row with colspan, so we need to find the actual header
        tables = list(html_helpers.extract_tables(artifact.text()))
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no HTML tables found",
                        target_label=self.target_label,
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        table_rows = tables[0].rows
        # Find the actual header (skip title rows with single cell)
        header_row_idx = None
        for i, row in enumerate(table_rows):
            if html_helpers.header_matches(row, list(self.table_keywords)):
                header_row_idx = i
                break

        if header_row_idx is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message=f"no table matching {self.table_keywords}",
                        target_label=self.target_label,
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        # Rebuild table with correct header
        from uk_jamaat_directory.ingest.extract.helpers.html import Table

        table_data = table_rows[header_row_idx:]
        table = Table(table_data)
        return self._extract_from_table(ctx, table)
