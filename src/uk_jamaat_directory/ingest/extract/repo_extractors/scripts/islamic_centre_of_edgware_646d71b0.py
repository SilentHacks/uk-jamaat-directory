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
    key = "islamic_centre_of_edgware_646d71b0"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("islamiccentreedgware.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    table_keywords = ("date", "iqamah")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 9,
        Prayer.MAGHRIB: 11,
        Prayer.ISHA: 13,
    }

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        # The site uses the daily-prayer-time-for-mosques plugin.
        # Monthly timetable is injected via AJAX into #monthlyTimetable.
        # Target the AJAX endpoint directly for the current month's table HTML
        # (two header rows: grouped prayer names, then Date/Day/Begins/Iqamah...).
        # Requires JS-capable fetch for RENDERED_HTML in smoke/runtime.
        self.targets = (
            TargetSpec(
                label="timetable",
                url=f"https://islamiccentreedgware.org/wp-admin/admin-ajax.php?action=get_monthly_timetable&month={now.month}&year={now.year}&display=",
                kind=TargetKind.RENDERED_HTML,
                requires_javascript=True,
            ),
        )

    def clean_cell(self, value: str) -> str:
        v = (value or "").strip()
        # Strip embedded hijri or markup (e.g. <p class="hijriDate">) from cells
        if "<p" in v.lower() or "dhū" in v.lower() or "hijri" in v.lower():
            if "<" in v:
                v = v.split("<", 1)[0]
            else:
                v = " ".join(v.split()[:3])
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
            # Sub-header row (index 1) contains the actual column labels including Iqamah
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
