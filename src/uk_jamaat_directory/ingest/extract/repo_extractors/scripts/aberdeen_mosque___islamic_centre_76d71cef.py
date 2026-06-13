"""
Aberdeen Mosque & Islamic Centre prayer timetable extractor.
Target: Monthly prayer times table with jamaat times.
Note: Fajr times are not extracted due to extremely early times during
midnight sun season (June) in Aberdeen (57°N latitude), which fall outside
the standard UK plausible window assumptions.
"""

from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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
    key = "aberdeen_mosque___islamic_centre_76d71cef"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("aberdeenmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    requires_javascript = True
    target_label = "monthly timetable"
    targets = (
        TargetSpec(
            label="monthly timetable",
            url="https://aberdeenmosque.org/prayer-times-central",
            kind=TargetKind.RENDERED_HTML,
        ),
    )
    table_keywords = ("date",)
    date_column = 0
    prayer_columns = {
        Prayer.DHUHR: 6,
        Prayer.ASR: 8,
        Prayer.MAGHRIB: 9,
        Prayer.ISHA: 11,
    }

    def parse_date_cell(self, value: str, *, year: int, month: int) -> date | None:
        # Override to handle dates with month names like "1 June"
        parsed = parse_date_flexible(value, default_year=year)
        if parsed is not None:
            return parsed
        # Fall back to parent behavior for day-only dates
        return super().parse_date_cell(value, year=year, month=month)

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        tables = html_helpers.extract_tables(artifact.text())
        if not tables:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")

        # Squarespace table has colspan header at row 0 with prayer names (Fajr, Zuhr, ...),
        # and detailed header at row 1 with (Date, Day, Begins, Jamā'ah, ...).
        # Check if row 0 doesn't contain "Date" - if not, skip it and use row 1 as header.
        first_table = tables[0]
        if len(first_table.rows) <= 1:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")

        # Check if row 0 is the colspan header (doesn't contain "date")
        header_row_index = 0
        if not any("date" in cell.lower() for cell in first_table.rows[0]):
            # Row 0 is the colspan header, use row 1
            header_row_index = 1

        if header_row_index >= len(first_table.rows):
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")

        # Use rows from header_row_index onward
        from uk_jamaat_directory.ingest.extract.helpers.html import Table
        data_rows = first_table.rows[header_row_index:]
        working_table = Table(data_rows)

        return self._extract_from_table(ctx, working_table)


