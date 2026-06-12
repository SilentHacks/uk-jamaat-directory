from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.pdf import extract_tables
from uk_jamaat_directory.ingest.extract.helpers.rows import carry_forward
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    ExtractorWarning,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)

PRAYER_COLUMNS: dict[Prayer, int] = {
    Prayer.FAJR: 3,
    Prayer.DHUHR: 6,
    Prayer.ASR: 8,
    Prayer.MAGHRIB: 9,
    Prayer.ISHA: 11,
}

MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_DATE_DAY = re.compile(r"\b(\d{1,2})\b")
_HEADER_MONTH = re.compile(r"([A-Za-z]+)")
_HEADER_YEAR = re.compile(r"[-\s]*(\d{2,4})\s*$")

_JUMUAH_RE = re.compile(
    r"Jumu'?ah\s+(\d{1,2})[.:](\d{2})\s*(am|pm)?",
    re.IGNORECASE,
)


def _parse_header_date(header_cell: str) -> tuple[int, int]:
    year = datetime.now().year
    month = datetime.now().month
    month_match = _HEADER_MONTH.match(header_cell.strip())
    if month_match:
        name = month_match.group(1).lower()
        month = MONTH_NAMES.get(name, month)
    year_match = _HEADER_YEAR.search(header_cell.strip())
    if year_match:
        yr = int(year_match.group(1))
        if yr < 100:
            yr += 2000
        year = yr
    return year, month


def _clean_carry_marker(value: str) -> str:
    cleaned = value.strip()
    if cleaned in ('" "', '"', "''", "\u201c", "\u201d", "-"):
        return ""
    return cleaned


def _next_fridays(today: date, count: int = 5) -> list[date]:
    """Return the next *count* Fridays starting from today."""
    days_ahead = 4 - today.weekday()
    if days_ahead < 0:
        days_ahead += 7
    first = today + timedelta(days=days_ahead)
    return [first + timedelta(weeks=i) for i in range(count)]


def _extract_jumuah_times(text: str) -> list[str]:
    """Extract Jumu'ah time strings like '1:30pm' from text."""
    times: list[str] = []
    for m in _JUMUAH_RE.finditer(text):
        h, min_str = int(m.group(1)), m.group(2)
        ampm = (m.group(3) or "").lower()
        if ampm:
            times.append(f"{h}:{min_str}{ampm}")
        else:
            times.append(f"{h}:{min_str}")
    if not times:
        alt = re.search(
            r"Jumu'?ah\s+(\d{1,2})[.:](\d{2})",
            text,
        )
        if alt:
            h, m = int(alt.group(1)), alt.group(2)
            times.append(f"{h}:{m}")
    return times


class Extractor(BaseMosqueWebsiteExtractor):
    key = "masjid_al_ummah_7f351bc0"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("abrahamicfoundation.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        today = datetime.now()
        prev = today.month - 1
        year = today.year
        if prev == 0:
            prev = 12
            year -= 1
        month = prev
        month_name = calendar.month_name[month]
        pdf_url = (
            f"https://legacy.abrahamicfoundation.org.uk/wp-content/uploads/2020/08/"
            f"{month:02d}-{month_name}-Salah-Timetable-Masjid-al-Ummah-1.pdf"
        )
        self._targets = (
            TargetSpec(
                label="homepage",
                url="http://abrahamicfoundation.org.uk/",
                kind=TargetKind.HTML,
            ),
            TargetSpec(
                label="timetable",
                url=pdf_url,
                kind=TargetKind.PDF,
            ),
        )
        super().__init__()

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        today = datetime.now().date()
        warnings: list[ExtractorWarning] = []
        result_rows: list[ExtractorRow] = []

        homepage = ctx.artifact("homepage")
        if homepage and homepage.body:
            jumuah_times = _extract_jumuah_times(homepage.text())
            if jumuah_times:
                fridays = _next_fridays(today, count=5)
                for jt in jumuah_times:
                    parsed = coerce_time(jt, prayer="jumuah")
                    if parsed is None:
                        parsed = coerce_time(jt, prayer="dhuhr")
                    if parsed:
                        for friday in fridays:
                            result_rows.append(
                                ExtractorRow(
                                    date=friday,
                                    prayer=Prayer.DHUHR,
                                    jamaat_time=parsed,
                                    timezone=ctx.timezone,
                                    evidence=ctx.evidence(
                                        target_label="homepage",
                                        extractor_key=self.key,
                                        extractor_version=self.version,
                                        raw_text=jt,
                                        selector="homepage banner",
                                    ),
                                )
                            )

        artifact = ctx.artifact("timetable")
        if not artifact.body:
            if result_rows:
                return ExtractorResult(rows=result_rows, warnings=warnings)
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        all_pages = extract_tables(artifact.body)
        if not all_pages or not all_pages[0]:
            if result_rows:
                return ExtractorResult(rows=result_rows, warnings=warnings)
            return ExtractorResult(rows=[], no_schedule_reason="no tables found in PDF")

        timetable_table = None
        for table in all_pages[0]:
            if not table or len(table) < 2:
                continue
            row0 = [str(c or "") for c in table[0]]
            has_fajr = any("fajr" in c.lower() for c in row0)
            has_iqamah = any("iqamah" in c.lower() for c in row0)
            if has_fajr and has_iqamah:
                timetable_table = table
                break

        if not timetable_table:
            if result_rows:
                return ExtractorResult(rows=result_rows, warnings=warnings)
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found in PDF")

        header = [str(c or "").strip() for c in timetable_table[0]]
        table_year, table_month = _parse_header_date(header[0])

        raw_rows: list[list[str]] = []
        for raw_row in timetable_table[1:]:
            row = [str(c or "").strip() for c in raw_row]
            if len(row) < 12:
                continue
            date_cell = row[0]
            if not date_cell:
                continue
            skip_words = {"note", "no true", "donate", "become"}
            if date_cell.lower() in skip_words or any(w in date_cell.lower() for w in skip_words):
                continue
            raw_rows.append(row)

        if not raw_rows:
            if result_rows:
                return ExtractorResult(rows=result_rows, warnings=warnings)
            return ExtractorResult(rows=[], no_schedule_reason="no data rows in PDF table")

        isha_adhan_col: list[str] = [
            raw_rows[i][10].strip() if len(raw_rows[i]) > 10 else "" for i in range(len(raw_rows))
        ]

        has_isha_iqa_col = len(header) >= 12

        for i in range(len(raw_rows)):
            raw_rows[i] = [_clean_carry_marker(c) for c in raw_rows[i]]

        cols = list(zip(*raw_rows, strict=True))
        carried_cols = [carry_forward(list(col)) for col in cols]
        carried_rows = [list(row) for row in zip(*carried_cols, strict=True)]

        for row_idx, row in enumerate(carried_rows):
            day_match = _DATE_DAY.search(row[0])
            if not day_match:
                continue
            day = int(day_match.group(1))
            try:
                row_date = date(table_year, table_month, day)
            except ValueError:
                continue

            for prayer, col_idx in PRAYER_COLUMNS.items():
                if col_idx >= len(row):
                    continue
                raw = row[col_idx].strip()
                if not raw:
                    continue

                if prayer == Prayer.ISHA:
                    orig_isha = isha_adhan_col[row_idx]
                    if not orig_isha or coerce_time(orig_isha, prayer="isha") is None:
                        if has_isha_iqa_col:
                            continue

                jamaat = coerce_time(raw, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=(f"{row_date} {prayer.value}: column {col_idx} {raw!r}"),
                            target_label="timetable",
                        )
                    )
                    continue

                result_rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(row),
                            selector=f"PDF row {row_idx + 2}",
                        ),
                    )
                )

        if not result_rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )

        seen: set[tuple[date, Prayer, int]] = set()
        deduped: list[ExtractorRow] = []
        for row in result_rows:
            sn = row.session_number
            key = (row.date, row.prayer, sn if sn is not None else 1)
            if key not in seen:
                seen.add(key)
                deduped.append(row)

        return ExtractorResult(rows=deduped, warnings=warnings)
