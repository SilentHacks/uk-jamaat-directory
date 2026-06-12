from __future__ import annotations

import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import (
    parse_date_flexible,
    parse_day_of_month,
    parse_month_name,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
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
    key = "faizan_e_islam_centre_c7d7d4ad"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("faizaneislam.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://faizaneislam.com/prayer-times/prayer-times-manchester/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 8,
        Prayer.DHUHR: 9,
        Prayer.ASR: 10,
        Prayer.MAGHRIB: 11,
        Prayer.ISHA: 12,
    }

    def clean_cell(self, value: str) -> str:
        v = (value or "").strip()
        v = re.sub(r"<[^>]+>", " ", v)
        v = " ".join(v.split())
        return v.strip()

    def parse_date_cell(self, value: str, *, year: int, month: int) -> date | None:
        v = (value or "").strip()
        if not v:
            return None
        # Handle forms like "1-Nov", "01-Nov", "1-nov", "1 Nov", "1/Nov", "12-Jun"
        m = re.match(r"^(\d{1,2})[\s\-/.]+([A-Za-z]{3,4})$", v)
        if m:
            day = int(m.group(1))
            mon_name = m.group(2).lower().rstrip(".")
            mon = parse_month_name(mon_name)
            if mon is not None and 1 <= day <= 31:
                try:
                    return date(year, mon, day)
                except ValueError:
                    return None
        # Fallbacks from base helpers
        parsed = parse_date_flexible(v, default_year=year)
        if parsed is not None:
            return parsed
        day = parse_day_of_month(v)
        if day is not None:
            try:
                return date(year, month, day)
            except ValueError:
                return None
        return None

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        for raw_table in tables:
            header_idx = None
            for i, row in enumerate(raw_table.rows):
                low = [c.lower() for c in row]
                if "date" in low and any("fajr" in c or "jama" in c for c in low):
                    header_idx = i
                    break
            if header_idx is None:
                continue
            header = [self.clean_cell(c) for c in raw_table.rows[header_idx]]
            body_rows = [[self.clean_cell(c) for c in r] for r in raw_table.rows[header_idx + 1 :]]
            if not body_rows:
                continue
            synthetic = html_helpers.Table([header] + body_rows)
            return self._extract_from_table(ctx, synthetic)
        return ExtractorResult(
            rows=[],
            warnings=[
                ExtractorWarning(
                    code="no_table",
                    message="no table with date/fajr or jamaat header row found",
                    target_label=self.target_label,
                )
            ],
            no_schedule_reason="timetable table not found",
        )
