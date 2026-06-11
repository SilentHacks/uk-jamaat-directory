from datetime import date, datetime, time

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_day_of_month
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

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

DAY_TRIGRAMS = frozenset({"mon", "tue", "wed", "thu", "fri", "sat", "sun"})

JAM_COLUMNS: dict[Prayer, int] = {
    Prayer.FAJR: 8,
    Prayer.DHUHR: 9,
    Prayer.ASR: 10,
    Prayer.MAGHRIB: 11,
    Prayer.ISHA: 12,
}

JUMUAH_SESSIONS: list[tuple[int, str, str]] = [
    (1, "1:30", "1st Jumma"),
    (2, "3:00", "2nd Jumma"),
]

WEEKEND_ASAR = "8:00"


class Extractor(BaseMosqueWebsiteExtractor):
    key = "blackpool_central_mosque_601edaf8"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("blackpool-mosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        now = date.today()
        self._year = now.year
        period_start = ((now.month - 1) // 2) * 2 + 1
        period_end = period_start + 1
        self._months = (period_start, period_end)
        start_name = MONTH_NAMES[period_start - 1]
        end_name = MONTH_NAMES[period_end - 1]
        url = (
            f"https://blackpool-mosque.co.uk/namaz-timings/"
            f"{start_name}%20{end_name}%20{now.year}.pdf"
        )
        self._targets = (
            TargetSpec(label="timetable", url=url, kind=TargetKind.PDF),
        )

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets

    def _month_from_text(self, text: str) -> int | None:
        for i, name in enumerate(MONTH_NAMES, start=1):
            if name.lower() in text.lower():
                return i
        return None

    def _map_row(self, row_data: list[str]) -> list[str] | None:
        """Try both column offsets (0 and 1) to map the PDF table row
        into 13 logical columns: [date, day, subh-sadiq, sunrise,
        zohar-start, asar-start, sunset, isha-start,
        fajr-j, zohar-j, asar-j, maghrib-j, isha-j]."""
        for offset in (0, 1):
            cells = []
            for i in range(13):
                idx = i * 3 + offset
                if idx < len(row_data):
                    cells.append(row_data[idx].strip())
                else:
                    cells.append("")
            day_test = cells[1].lower()[:3]
            if day_test in DAY_TRIGRAMS:
                return cells
            if cells[0].isdigit() and 1 <= int(cells[0]) <= 31:
                return cells
        return None

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        page_tables = pdf_helpers.extract_tables(artifact.body)
        full_text = pdf_helpers.extract_text(artifact.body)
        pages_text = full_text.split("\x0c")
        warnings: list[ExtractorWarning] = []
        all_rows: list[ExtractorRow] = []

        page_months: list[int | None] = []
        for pt in pages_text:
            page_months.append(self._month_from_text(pt))

        for page_idx, tables_on_page in enumerate(page_tables):
            month = page_months[page_idx] if page_idx < len(page_months) else None
            if month is None:
                month = self._months[page_idx] if page_idx < 2 else self._months[0]

            for raw_table in tables_on_page:
                cleaned = [
                    [(cell or "") for cell in row]
                    for row in raw_table
                    if row
                ]
                if len(cleaned) < 3:
                    continue

                # Map all rows after header rows (0=spanning, 1=column) to 13 columns
                data_rows: list[list[str]] = []
                for raw_row in cleaned[2:]:
                    if not any(c.strip() for c in raw_row):
                        continue
                    mapped = self._map_row(raw_row)
                    if mapped:
                        data_rows.append(mapped)

                if not data_rows:
                    continue

                # Carry forward merged jamaat cells
                for col_idx in range(8, 13):
                    vals = carry_forward(
                        row[col_idx] if col_idx < len(row) else ""
                        for row in data_rows
                    )
                    for i, v in enumerate(vals):
                        data_rows[i][col_idx] = v

                for row_data in data_rows:
                    date_val = row_data[0]
                    day_val = row_data[1]

                    if not date_val:
                        continue

                    day_num = parse_day_of_month(date_val)
                    if day_num is None:
                        continue

                    try:
                        d = date(self._year, month, day_num)
                    except ValueError:
                        continue

                    day_key = day_val.lower()[:3]
                    is_weekend = day_key in ("sat", "sun")
                    is_friday = day_key == "fri"

                    for prayer, col in JAM_COLUMNS.items():
                        raw = row_data[col].strip() if col < len(row_data) else ""
                        if not raw:
                            continue
                        t = coerce_time(raw, prayer=prayer.value)
                        if t is None:
                            warnings.append(ExtractorWarning(
                                code="unparseable_time",
                                message=f"{d} {prayer.value}: {raw!r}",
                                target_label="timetable",
                            ))
                            continue

                        if prayer == Prayer.ASR and is_weekend:
                            override = coerce_time(
                                WEEKEND_ASAR, prayer=prayer.value
                            )
                            if override:
                                t = override

                        all_rows.append(ExtractorRow(
                            date=d,
                            prayer=prayer,
                            jamaat_time=t,
                            timezone=ctx.timezone or "Europe/London",
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=" | ".join(row_data),
                                selector=f"PDF page {page_idx + 1}",
                            ),
                        ))

                    if is_friday:
                        for session_num, raw_time, label in JUMUAH_SESSIONS:
                            jt = coerce_time(
                                raw_time, prayer=Prayer.JUMUAH.value
                            )
                            if jt:
                                all_rows.append(ExtractorRow(
                                    date=d,
                                    prayer=Prayer.JUMUAH,
                                    jamaat_time=jt,
                                    session_number=session_num,
                                    session_label=label,
                                    timezone=ctx.timezone or "Europe/London",
                                    evidence=ctx.evidence(
                                        target_label="timetable",
                                        extractor_key=self.key,
                                        extractor_version=self.version,
                                    ),
                                ))

        if not all_rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows in PDF",
            )
        return ExtractorResult(rows=all_rows, warnings=warnings)
