from __future__ import annotations

from datetime import datetime

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
    key = "riverside_muslim_association_0b681e59"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("riversidemuslimassociation.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # The /prayer-timetable/ page uses the daily-prayer-time-for-mosques plugin.
        # The monthly timetable is injected client-side into #monthlyTimetable via
        # admin-ajax get_monthly_timetable (two header rows + data). We target the
        # public page and rely on a JS-capable fetch (RENDERED_HTML) to obtain the
        # rendered table HTML for the current month.
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://www.riversidemuslimassociation.org/prayer-timetable/",
                kind=TargetKind.RENDERED_HTML,
                requires_javascript=True,
            ),
        )

    table_keywords = ("date", "iqamah")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 8,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }

    def clean_cell(self, value: str) -> str:
        v = (value or "").strip()
        # Strip any embedded markup or extra whitespace (e.g. hijri notes if present)
        if "<" in v:
            v = html_helpers.strip_tags(v)
        v = " ".join(v.split())
        return v.strip()

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        # DPT monthly: row 0 = grouped prayer names (colspans), row 1 = sub-header
        # with "Date", "Day", "Begins", "Iqamah", ... . Use sub-header as header.
        for raw_table in html_helpers.extract_tables(html):
            rows = raw_table.rows
            if len(rows) < 3:
                continue
            if html_helpers.header_matches(rows[1], list(self.table_keywords)):
                effective = html_helpers.Table([rows[1]] + rows[2:])
                return self._extract_from_table(ctx, effective)
        # Fallback: let base report cleanly if no matching table structure.
        return ExtractorResult(
            rows=[],
            warnings=[
                ExtractorWarning(
                    code="no_table",
                    message="no dpt monthly timetable structure found",
                    target_label=self.target_label,
                )
            ],
            no_schedule_reason="timetable table not found",
        )
