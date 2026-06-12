"""Declarative base classes for repo extractor scripts.

Generated scripts should subclass these and supply *configuration*, not
parsing code. The bases handle table discovery, header mapping, date and
time parsing (prayer-aware am/pm inference), evidence, warnings, and the
``no_schedule_reason`` bookkeeping that the validator requires.

A typical authored script becomes ~30 lines:

    class Extractor(TableTimetableExtractor):
        key = "example_mosque_12345678"
        version = "2026.06.10.1"
        source_match = SourceMatch(domains=("example.com",))
        refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
        targets = (TargetSpec(label="timetable", url="https://example.com/times",
                              kind=TargetKind.HTML),)
        table_keywords = ("date", "fajr")
        date_column = "date"
        prayer_columns = {
            Prayer.FAJR: "fajr jamaat",
            Prayer.DHUHR: "zuhr jamaat",
            Prayer.ASR: "asr jamaat",
            Prayer.MAGHRIB: "maghrib",
            Prayer.ISHA: "isha jamaat",
        }
"""

from __future__ import annotations

from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import (
    parse_date_flexible,
    parse_day_of_month,
)
from uk_jamaat_directory.ingest.extract.helpers.html import Table
from uk_jamaat_directory.ingest.extract.helpers.rows import carry_forward
from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS, coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    ExtractorWarning,
)


class _TabularTimetableMixin:
    """Shared row-mapping logic for HTML and PDF table extractors."""

    # --- configuration (override in subclasses) ---
    target_label: str = "timetable"
    #: keywords that must all appear in the table's header row
    table_keywords: tuple[str, ...] = ("date",)
    #: header keyword (str) or column index (int) of the date column
    date_column: str | int = "date"
    #: Prayer -> header keyword (str) or column index (int) of the JAMAAT column
    prayer_columns: dict[Prayer, str | int] = {}
    #: optional Prayer -> column for adhan/start times
    start_columns: dict[Prayer, str | int] = {}
    #: carry blank cells forward from the previous row (merged-cell PDFs)
    use_carry_forward: bool = False

    # --- hooks (override for site quirks) ---
    def clean_cell(self, value: str) -> str:
        return value.strip()

    def accept_row(self, row: list[str], row_date: date) -> bool:
        return True

    def current_year(self, ctx: ExtractContext) -> int:
        return datetime.now().year

    def current_month(self, ctx: ExtractContext) -> int:
        """Month assumed when the date column holds only a day number."""
        return datetime.now().month

    def parse_date_cell(self, value: str, *, year: int, month: int) -> date | None:
        parsed = parse_date_flexible(value, default_year=year)
        if parsed is not None:
            return parsed
        # Monthly tables often print just the day number ("1", "21st").
        day = parse_day_of_month(value)
        if day is None:
            return None
        try:
            return date(year, month, day)
        except ValueError:
            return None

    # --- implementation ---
    def _column_index(self, header: list[str], spec: str | int) -> int | None:
        if isinstance(spec, int):
            return spec if 0 <= spec < len(header) else None
        needle = spec.lower()
        for idx, cell in enumerate(header):
            if needle in cell.lower():
                return idx
        return None

    def _extract_from_table(self, ctx: ExtractContext, table: Table) -> ExtractorResult:
        header = [self.clean_cell(cell) for cell in table.header]
        warnings: list[ExtractorWarning] = []

        date_idx = self._column_index(header, self.date_column)
        if date_idx is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_date_column",
                        message=f"date column {self.date_column!r} not found in {header}",
                        target_label=self.target_label,
                    )
                ],
                no_schedule_reason="date column not found",
            )

        prayer_idx: dict[Prayer, int] = {}
        for prayer, spec in self.prayer_columns.items():
            idx = self._column_index(header, spec)
            if idx is None:
                warnings.append(
                    ExtractorWarning(
                        code="missing_prayer_column",
                        message=f"column {spec!r} for {prayer.value} not found",
                        target_label=self.target_label,
                    )
                )
            else:
                prayer_idx[prayer] = idx
        start_idx: dict[Prayer, int] = {}
        for prayer, spec in self.start_columns.items():
            idx = self._column_index(header, spec)
            if idx is not None:
                start_idx[prayer] = idx
        if not prayer_idx:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no prayer columns found",
            )

        body = [[self.clean_cell(cell) for cell in row] for row in table.body()]
        if self.use_carry_forward and body:
            width = max(len(row) for row in body)
            padded = [row + [""] * (width - len(row)) for row in body]
            columns = [carry_forward(col) for col in zip(*padded, strict=True)]
            body = [list(row) for row in zip(*columns, strict=True)]

        year = self.current_year(ctx)
        month = self.current_month(ctx)
        rows: list[ExtractorRow] = []
        for row_number, row in enumerate(body, start=1):
            if date_idx >= len(row):
                continue
            row_date = self.parse_date_cell(row[date_idx], year=year, month=month)
            if row_date is None or not self.accept_row(row, row_date):
                continue
            for prayer, idx in prayer_idx.items():
                raw = row[idx] if idx < len(row) else ""
                if not raw:
                    continue
                jamaat = coerce_time(raw, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {raw!r}",
                            target_label=self.target_label,
                        )
                    )
                    continue
                window = PLAUSIBLE_WINDOWS.get(prayer.value)
                if window and not (window[0] <= jamaat <= window[1]):
                    # Bad upstream cell (e.g. a 23:30 "Fajr"); drop the row
                    # rather than publish it or fail the whole source.
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{row_date} {prayer.value}: {raw!r} outside plausible window",
                            target_label=self.target_label,
                        )
                    )
                    continue
                start = None
                sidx = start_idx.get(prayer)
                if sidx is not None and sidx < len(row) and row[sidx]:
                    start = coerce_time(row[sidx], prayer=prayer.value)
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        start_time=start,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label=self.target_label,
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(row),
                            selector=f"table row {row_number}",
                        ),
                    )
                )
        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=rows, warnings=warnings)


class TableTimetableExtractor(_TabularTimetableMixin, BaseMosqueWebsiteExtractor):
    """Declarative extractor for an HTML table timetable."""

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        table = html_helpers.find_table(artifact.text(), header_keywords=list(self.table_keywords))
        if table is None:
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
        return self._extract_from_table(ctx, table)


class PdfTableTimetableExtractor(_TabularTimetableMixin, BaseMosqueWebsiteExtractor):
    """Declarative extractor for a PDF table timetable."""

    use_carry_forward = True

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        for page_tables in pdf_helpers.extract_tables(artifact.body):
            for raw_table in page_tables:
                cleaned = [[(cell or "") for cell in row] for row in raw_table if row]
                if not cleaned:
                    continue
                table = Table(cleaned)
                if html_helpers.header_matches(table.header, list(self.table_keywords)):
                    return self._extract_from_table(ctx, table)
        return ExtractorResult(
            rows=[],
            warnings=[
                ExtractorWarning(
                    code="no_table",
                    message=f"no PDF table matching {self.table_keywords}",
                    target_label=self.target_label,
                )
            ],
            no_schedule_reason="timetable table not found in PDF",
        )


class StubbedOcrExtractor(BaseMosqueWebsiteExtractor):
    """Extractor for image timetables, stubbed until OCR is implemented.

    Subclasses only declare ``key``, ``version``, ``source_match``,
    ``refresh_policy`` and ``targets`` (with ``requires_ocr=True``).
    """

    no_schedule_reason: str = "image target — awaiting OCR"

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        return ExtractorResult(rows=[], no_schedule_reason=self.no_schedule_reason)


class StubbedPdfExtractor(BaseMosqueWebsiteExtractor):
    """Extractor for PDF timetables, stubbed until PDF parsing is wired up.

    PDFs are deliberately not parsed yet: authored scripts only declare the
    target (with ``requires_pdf=True``) so the source is recorded and can be
    revisited when a PDF parser lands. Mirrors :class:`StubbedOcrExtractor`.
    """

    no_schedule_reason: str = "pdf target — awaiting parser"

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        return ExtractorResult(rows=[], no_schedule_reason=self.no_schedule_reason)
