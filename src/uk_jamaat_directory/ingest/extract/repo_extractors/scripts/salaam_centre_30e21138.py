from __future__ import annotations

import re
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
    key = "salaam_centre_30e21138"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("sicm.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    table_keywords = ("date", "iqamah")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 5,
        Prayer.ASR: 7,
        Prayer.MAGHRIB: 8,
    }

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        # The site uses the daily-prayer-time-for-mosques plugin.
        # The #monthlyTimetable div is populated via AJAX into a fragment table.
        # Target the AJAX endpoint for the current month (two header rows + data).
        # Requires JS-capable fetch (RENDERED_HTML) due to dynamic injection and
        # server protections on the endpoint.
        self.targets = (
            TargetSpec(
                label="timetable",
                url=f"https://sicm.org.uk/wp-admin/admin-ajax.php?action=get_monthly_timetable&month={now.month}&year={now.year}",
                kind=TargetKind.RENDERED_HTML,
                requires_javascript=True,
            ),
        )

    def clean_cell(self, value: str) -> str:
        v = (value or "").strip()
        # Remove any embedded markup or extra whitespace from cells
        if "<" in v:
            v = re.sub(r"<[^>]+>", "", v)
        v = " ".join(v.split())
        return v.strip()

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        for raw_table in html_helpers.extract_tables(html):
            rows = raw_table.rows
            if len(rows) < 2:
                continue
            # Row 1 (0-based) is the sub-header containing "Date", "Iqamah" etc.
            if html_helpers.header_matches(rows[1], list(self.table_keywords)):
                effective = html_helpers.Table([rows[1]] + rows[2:])
                return self._extract_from_table(ctx, effective)
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
