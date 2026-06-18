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

import json
import re
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


class MasjidboxReduxExtractor(BaseMosqueWebsiteExtractor):
    """Declarative extractor for masjidbox.com prayer-times pages.

    masjidbox SSR pages embed the schedule as a percent-encoded JSON blob in
    ``window.REDUX_STATE``. The ``iqamah`` object holds the congregation
    (jamaat) times as ISO 8601 strings with the local UTC offset, so
    ``datetime.fromisoformat(...).time()`` yields the correct local time. The
    sibling ``adhan`` values are prayer start times and are deliberately not
    used as jamaat times.

    Subclasses only supply ``key``, ``version``, ``source_match``,
    ``refresh_policy`` and ``targets`` (a single masjidbox
    ``prayer-times/<slug>`` URL with ``kind=TargetKind.HTML``).
    """

    target_label: str = "timetable"
    _PRAYERS: dict[Prayer, str] = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "dhuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()

        match = re.search(r"window\.REDUX_STATE\s*=\s*'([^']+)'", html)
        if not match:
            return ExtractorResult(rows=[], no_schedule_reason="REDUX_STATE not found")
        try:
            decoded = re.sub(
                r"%([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), match.group(1)
            )
            data = json.loads(decoded)
        except Exception:
            return ExtractorResult(rows=[], no_schedule_reason="REDUX_STATE parse failed")

        timetable = (
            data.get("masjidbox", {}).get("masjidboxAthany", {}).get("timetable", [])
        )
        if not timetable:
            return ExtractorResult(
                rows=[], no_schedule_reason="timetable not found in REDUX_STATE"
            )

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        for day in timetable:
            iqamah = day.get("iqamah") or {}
            jumuah = iqamah.get("jumuah")
            if isinstance(jumuah, list):
                for session, value in enumerate(jumuah, start=1):
                    if not value:
                        continue
                    try:
                        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    except Exception:
                        continue
                    rows.append(
                        ExtractorRow(
                            date=dt.date(),
                            prayer=Prayer.JUMUAH,
                            jamaat_time=dt.time(),
                            session_number=session,
                            session_label=f"session {session}",
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label=self.target_label,
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=str(value),
                                selector=f"REDUX_STATE iqamah.jumuah[{session - 1}]",
                            ),
                        )
                    )
            for prayer, key in self._PRAYERS.items():
                value = iqamah.get(key)
                if not value:
                    continue
                try:
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except Exception:
                    warnings.append(
                        ExtractorWarning(
                            code="bad_jamaat",
                            message=f"{prayer.value}: {value!r}",
                            target_label=self.target_label,
                        )
                    )
                    continue
                window = PLAUSIBLE_WINDOWS.get(prayer.value)
                if window and not (window[0] <= dt.time() <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=(
                                f"{dt.date()} {prayer.value}: {value!r} "
                                "outside plausible window"
                            ),
                            target_label=self.target_label,
                        )
                    )
                    continue
                rows.append(
                    ExtractorRow(
                        date=dt.date(),
                        prayer=prayer,
                        jamaat_time=dt.time(),
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label=self.target_label,
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=value,
                            selector=f"REDUX_STATE iqamah.{key}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no iqamah times found"
            )
        return ExtractorResult(rows=rows, warnings=warnings)


class MawaqitConfDataExtractor(BaseMosqueWebsiteExtractor):
    """Declarative extractor for mawaqit.net widget/page targets.

    mawaqit embeds the whole year in a ``confData`` JSON object in the page.
    ``iqamaCalendar`` holds the congregation (iqama/jamaat) times — a list of
    12 month dicts keyed by day-of-month, each value ``[fajr, dhuhr, asr,
    maghrib, isha]``. Values are absolute ``HH:MM`` or a relative offset
    (e.g. ``"+20"``) from the matching ``calendar`` (adhan) time. ``jumua``
    /``jumua2``/``jumua3`` give the Friday congregation times. ``calendar``
    (adhan/start times) is deliberately not used as jamaat.

    Subclasses only supply ``key``, ``version``, ``source_match``,
    ``refresh_policy`` and ``targets``.
    """

    target_label: str = "timetable"
    # iqamaCalendar index -> calendar (adhan) index for relative offsets.
    # calendar is [fajr, shuruq, dhuhr, asr, maghrib, isha]; iqama skips shuruq.
    _IQAMA_PRAYERS = (Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA)
    _ADHAN_INDEX = (0, 2, 3, 4, 5)

    def _resolve_time(
        self, raw: str, adhan: str | None, prayer: str
    ) -> "datetime.time | None":
        from uk_jamaat_directory.ingest.extract.helpers.relative import (
            add_minutes,
            parse_offset_minutes,
        )
        from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time

        raw = (raw or "").strip()
        if not raw:
            return None
        if ":" in raw:
            return coerce_time(raw, prayer=prayer)
        offset = parse_offset_minutes(raw)
        if offset is None or not adhan:
            return None
        base = coerce_time(adhan, prayer=prayer)
        if base is None:
            return None
        return add_minutes(base, offset)

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        match = re.search(r"confData\s*=\s*(\{.*?\})\s*[;<]", html, re.S)
        if not match:
            return ExtractorResult(rows=[], no_schedule_reason="confData not found")
        try:
            data = json.loads(match.group(1))
        except Exception:
            return ExtractorResult(rows=[], no_schedule_reason="confData parse failed")

        iqama_cal = data.get("iqamaCalendar")
        adhan_cal = data.get("calendar")
        if not isinstance(iqama_cal, list) or not iqama_cal:
            return ExtractorResult(rows=[], no_schedule_reason="iqamaCalendar not found")

        year = datetime.now().year
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        jumua_times = [data.get("jumua"), data.get("jumua2"), data.get("jumua3")]
        jumua_times = [t for t in jumua_times if t]

        for month_index, month in enumerate(iqama_cal, start=1):
            if not isinstance(month, dict):
                continue
            adhan_month = (
                adhan_cal[month_index - 1]
                if isinstance(adhan_cal, list) and len(adhan_cal) >= month_index
                else {}
            )
            for day_str, values in month.items():
                try:
                    day = int(day_str)
                    row_date = date(year, month_index, day)
                except (ValueError, TypeError):
                    continue
                if not isinstance(values, list):
                    continue
                adhan_values = adhan_month.get(day_str) if isinstance(adhan_month, dict) else None
                for i, prayer in enumerate(self._IQAMA_PRAYERS):
                    if i >= len(values):
                        continue
                    adhan = None
                    if isinstance(adhan_values, list) and self._ADHAN_INDEX[i] < len(adhan_values):
                        adhan = adhan_values[self._ADHAN_INDEX[i]]
                    jamaat = self._resolve_time(values[i], adhan, prayer.value)
                    if jamaat is None:
                        continue
                    window = PLAUSIBLE_WINDOWS.get(prayer.value)
                    if window and not (window[0] <= jamaat <= window[1]):
                        continue
                    rows.append(
                        ExtractorRow(
                            date=row_date,
                            prayer=prayer,
                            jamaat_time=jamaat,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label=self.target_label,
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=str(values[i]),
                                selector=(
                                    f"confData.iqamaCalendar"
                                    f"[{month_index - 1}][{day_str}][{i}]"
                                ),
                            ),
                        )
                    )
                # Friday jumua congregations
                if row_date.weekday() == 4 and jumua_times:
                    for session, value in enumerate(jumua_times, start=1):
                        jt = self._resolve_time(str(value), None, "jumuah")
                        if jt is None:
                            continue
                        rows.append(
                            ExtractorRow(
                                date=row_date,
                                prayer=Prayer.JUMUAH,
                                jamaat_time=jt,
                                session_number=session,
                                session_label=f"session {session}",
                                timezone=ctx.timezone,
                                evidence=ctx.evidence(
                                    target_label=self.target_label,
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    raw_text=str(value),
                                    selector=f"confData.jumua[{session}]",
                                ),
                            )
                        )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no iqama times found"
            )
        return ExtractorResult(rows=rows, warnings=warnings)


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
