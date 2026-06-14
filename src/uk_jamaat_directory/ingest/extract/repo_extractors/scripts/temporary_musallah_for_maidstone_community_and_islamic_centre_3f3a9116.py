from __future__ import annotations

from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
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
    key = "temporary_musallah_for_maidstone_community_and_islamic_centre_3f3a9116"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("maidstonemosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    table_keywords = ("date", "iqamah")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 8,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        # Use the plugin AJAX endpoint with query params so a GET (or browser nav)
        # can retrieve the monthly table fragment. The smoke test / runtime will
        # use fetch_rendered_html because we mark requires_javascript.
        self.targets = (
            TargetSpec(
                label="timetable",
                url=f"https://maidstonemosque.com/wp-admin/admin-ajax.php?action=get_monthly_timetable&month={now.month}&display=",
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

    def accept_row(self, row: list[str], row_date: date) -> bool:
        coerced: list = []
        for p in (Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA):
            idx = self.prayer_columns.get(p)
            if idx is None or idx >= len(row):
                continue
            raw = row[idx]
            if not raw:
                continue
            t = coerce_time(raw, prayer=p.value)
            if t is not None:
                coerced.append(t)
        if len(coerced) >= 2 and coerced != sorted(coerced):
            return False
        return True

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        # The AJAX response (or rendered equivalent) is a div wrapper containing
        # the table. The table has two header rows: the first groups prayer names,
        # the second (sub-header) has the actual labels including "Date" and "Iqamah".
        # Re-wrap so the sub-header row becomes the effective header for the base.
        for raw_table in html_helpers.extract_tables(html):
            rows = raw_table.rows
            if len(rows) < 2:
                continue
            if html_helpers.header_matches(rows[1], list(self.table_keywords)):
                effective = html_helpers.Table([rows[1]] + rows[2:])
                return self._extract_from_table(ctx, effective)
        # Fallback to standard behaviour (will surface "no table" if needed)
        return super().extract(ctx)
