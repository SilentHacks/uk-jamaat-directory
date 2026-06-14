from __future__ import annotations

import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_day_of_month, parse_month_name
from uk_jamaat_directory.ingest.extract.helpers.html import Table
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
    PdfTableTimetableExtractor,
)


class Extractor(PdfTableTimetableExtractor):
    key = "york_mosque_601fac42"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("yorkmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    table_keywords = ("date", "day")
    date_column: str | int = 0
    prayer_columns: dict[Prayer, str | int] = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 8,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }
    use_carry_forward = False

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        mon_name = now.strftime("%B")
        yy = now.year % 100
        base = "https://yorkmosque.com/wp-content/uploads/2025/12/"
        if now.month == 4:
            fname = f"{mon_name}-{yy}-Salah-Times-1.pdf"
        else:
            fname = f"{mon_name}-{yy}-Salah-Times.pdf"
        url = base + fname
        self.targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )
        self._target_year: int | None = None
        self._target_month: int | None = None
        self._seen_high_day: bool = False

    def clean_cell(self, value: str) -> str:
        v = (value or "").replace("\n", " ").strip()
        v = v.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
        return v

    def _extract_year_month_from_pdf(self, ctx: ExtractContext) -> tuple[int, int]:
        try:
            artifact = ctx.artifact(self.target_label)
            txt = pdf_helpers.extract_text(artifact.body) or ""
        except Exception:
            txt = ""
        year = datetime.now().year
        month = datetime.now().month
        m = re.search(r"\b(20\d{2})\b", txt)
        if m:
            year = int(m.group(1))
        m2 = re.search(
            r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
            r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\b",
            txt,
            re.IGNORECASE,
        )
        if m2:
            mon = parse_month_name(m2.group(1))
            if mon is not None:
                month = mon
        try:
            url = ctx.artifact(self.target_label).target_url or ""
        except Exception:
            url = ""
        if not m:
            m = re.search(r"(20\d{2})", url)
            if m:
                year = int(m.group(1))
        if not m2:
            m2 = re.search(
                r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
                r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\b",
                url,
                re.IGNORECASE,
            )
            if m2:
                mon = parse_month_name(m2.group(1))
                if mon is not None:
                    month = mon
        if year < 2000:
            m3 = re.search(r"-(\d{2})-Salah", url)
            if m3:
                yy = int(m3.group(1))
                year = 2000 + yy
        return year, month

    def current_year(self, ctx: ExtractContext) -> int:
        y, _ = self._extract_year_month_from_pdf(ctx)
        return y

    def current_month(self, ctx: ExtractContext) -> int:
        _, m = self._extract_year_month_from_pdf(ctx)
        return m

    def parse_date_cell(self, value: str, *, year: int, month: int):
        # The PDF table contains a trailing preview of the next month after the
        # last day of the target month. We track when we have seen a high day
        # number and then a day reset to 1; any "1" after that is considered
        # next-month and dropped.
        d = parse_day_of_month(value)
        if d is None:
            return None
        if self._target_month is None:
            self._target_year = year
            self._target_month = month
            self._seen_high_day = False
        if d >= 28:
            self._seen_high_day = True
        if self._seen_high_day and d == 1:
            # this is the rollover preview for next month — reject
            return None
        try:
            return date(year, month, d)
        except ValueError:
            return None

    def accept_row(self, row: list[str], row_date) -> bool:
        # Accept only rows whose date cell is a pure day number (or day+ordinal) and whose
        # first two cells are a day-of-month and a 3-letter weekday.
        if not row:
            return False
        dc = (row[0] or "").strip()
        if not dc:
            return False
        if parse_day_of_month(dc) is None:
            return False
        if len(row) < 2:
            return False
        day2 = (row[1] or "").strip().lower()
        if day2 not in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}:
            return False
        return True

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        for page_tables in pdf_helpers.extract_tables(artifact.body):
            for raw_table in page_tables:
                cleaned = [
                    [(cell or "").strip() for cell in row]
                    for row in raw_table
                    if any((c or "").strip() for c in row)
                ]
                if not cleaned:
                    continue
                header_row_idx = None
                for i, row in enumerate(cleaned):
                    low = [(c or "").lower() for c in row]
                    if "date" in low and "day" in low:
                        header_row_idx = i
                        break
                if header_row_idx is None:
                    continue
                sub_rows = cleaned[header_row_idx:]
                table = Table(sub_rows)
                if html_helpers.header_matches(table.header, list(self.table_keywords)):
                    return self._extract_from_table(ctx, table)
        return ExtractorResult(
            rows=[],
            warnings=[
                ExtractorWarning(
                    code="no_table",
                    message="no PDF table matching the expected header layout",
                    target_label=self.target_label,
                )
            ],
            no_schedule_reason="timetable table not found in PDF",
        )
