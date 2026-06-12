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
    key = "st_albans_islamic_centre_381c96bd"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("icsta.org.uk",))
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
        # The monthly table is injected via AJAX get_monthly_timetable.
        # We target the AJAX endpoint directly so the artifact contains the
        # rendered monthly table HTML (two header rows: grouped names then
        # Date/Day/Begins/Iqamah/...). Requires JS fetch in smoke/runtime.
        self.targets = (
            TargetSpec(
                label="timetable",
                url=f"https://icsta.org.uk/wp-admin/admin-ajax.php?action=get_monthly_timetable&month={now.month}&year={now.year}&display=",
                kind=TargetKind.RENDERED_HTML,
                requires_javascript=True,
            ),
        )

    def clean_cell(self, value: str) -> str:
        v = value
        if "<p" in v.lower() or "dhū" in v.lower() or "hijri" in v.lower():
            if "<" in v:
                v = v.split("<", 1)[0]
            else:
                v = " ".join(v.split()[:3])
        return v.strip()

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        for raw_table in html_helpers.extract_tables(html):
            rows = raw_table.rows
            if len(rows) < 2:
                continue
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
