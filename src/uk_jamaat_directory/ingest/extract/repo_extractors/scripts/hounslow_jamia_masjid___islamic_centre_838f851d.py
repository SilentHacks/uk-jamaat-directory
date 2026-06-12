from __future__ import annotations

import re
from datetime import date, datetime

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
    key = "hounslow_jamia_masjid___islamic_centre_838f851d"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("hounslowmasjid.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # The /prayer/ page uses the daily-prayer-time-for-mosques WP plugin.
        # The monthly timetable is injected client-side into #monthlyTimetable via
        # admin-ajax (two header rows + data rows with explicit Iqamah/jamaat columns).
        # Target the public page with a JS-capable fetch (RENDERED_HTML) to obtain
        # the rendered table for the current month. This is the broadest timetable.
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://hounslowmasjid.co.uk/prayer/",
                kind=TargetKind.RENDERED_HTML,
                requires_javascript=True,
            ),
        )
        self._determined_year: int | None = None
        self._determined_month: int | None = None

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
        if "<" in v:
            v = html_helpers.strip_tags(v)
        v = " ".join(v.split())
        return v.strip()

    def current_year(self, ctx: ExtractContext) -> int:
        if self._determined_year:
            return self._determined_year
        return super().current_year(ctx)

    def current_month(self, ctx: ExtractContext) -> int:
        if self._determined_month:
            return self._determined_month
        return super().current_month(ctx)

    def parse_date_cell(self, value: str, *, year: int, month: int) -> date | None:
        # Neutralize any embedded year in the cell so we attribute to the
        # page's displayed year/month (or now()).
        cleaned = re.sub(r"\b20\d{2}\b", "", value)
        parsed = super().parse_date_cell(cleaned, year=year, month=month)
        if parsed is not None:
            if self._determined_year and parsed.year != self._determined_year:
                try:
                    return parsed.replace(year=self._determined_year)
                except ValueError:
                    pass
            return parsed
        return super().parse_date_cell(value, year=year, month=month)

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()

        # Determine displayed month/year from the DPT header, e.g.
        # <h3 class='printSiteName'>Hounslow Jamia Masjid and Islamic Centre</br>
        # <span style='color:green'>Jun, 2026</span></h3>
        year = datetime.now().year
        month = datetime.now().month
        m = re.search(
            r"(?i)(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[,\s]+(20\d{2})",
            html,
        )
        if m:
            mon_map = {
                "jan": 1,
                "feb": 2,
                "mar": 3,
                "apr": 4,
                "may": 5,
                "jun": 6,
                "jul": 7,
                "aug": 8,
                "sep": 9,
                "oct": 10,
                "nov": 11,
                "dec": 12,
            }
            month = mon_map.get(m.group(1).lower()[:3], month)
            year = int(m.group(2))
        self._determined_year = year
        self._determined_month = month

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
