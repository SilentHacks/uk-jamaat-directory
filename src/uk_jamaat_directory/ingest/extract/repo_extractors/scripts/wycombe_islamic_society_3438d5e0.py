from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
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

DATE_COL = 0
PRAYER_COLUMNS: dict[Prayer, int] = {
    Prayer.FAJR: 3,
    Prayer.DHUHR: 6,
    Prayer.ASR: 8,
    Prayer.MAGHRIB: 10,
    Prayer.ISHA: 12,
}
START_COLUMNS: dict[Prayer, int] = {
    Prayer.FAJR: 2,
    Prayer.DHUHR: 5,
    Prayer.ASR: 7,
    Prayer.MAGHRIB: 9,
    Prayer.ISHA: 11,
}

SECOND_HEADER_KEYWORDS = frozenset({"date", "day", "begins", "jama'ah"})


def _fix_broken_table(html: str) -> str:
    if "<table" in html and "</table>" not in html:
        html = html + "</table>"
    return html


def _is_header_row(row: list[str]) -> bool:
    tokens = {cell.strip().lower() for cell in row if cell.strip()}
    return bool(tokens & SECOND_HEADER_KEYWORDS)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "wycombe_islamic_society_3438d5e0"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("wise-web.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        self._targets = (
            TargetSpec(
                label="timetable",
                url=(
                    f"http://www.wise-web.org/wp-admin/admin-ajax.php"
                    f"?action=get_monthly_timetable&month={now.month}&display="
                ),
                kind=TargetKind.HTML,
            ),
        )

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = _fix_broken_table(artifact.text())
        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no table found in monthly timetable HTML",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        table = tables[0]
        all_rows = table.rows
        if len(all_rows) < 2:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="too_few_rows",
                        message=f"table has only {len(all_rows)} rows",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="too few table rows",
            )

        year = datetime.now().year
        parsed_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        for row_number, row in enumerate(all_rows, start=1):
            if len(row) <= max(PRAYER_COLUMNS.values()):
                continue
            if _is_header_row(row):
                continue
            raw_date = row[DATE_COL]
            row_date = parse_date_flexible(raw_date, default_year=year)
            if row_date is None:
                warnings.append(
                    ExtractorWarning(
                        code="bad_date",
                        message=f"row {row_number}: unparseable date {raw_date!r}",
                        target_label="timetable",
                    )
                )
                continue
            for prayer, col in PRAYER_COLUMNS.items():
                raw = row[col].strip()
                if not raw:
                    continue
                jamaat = coerce_time(raw, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                start = None
                sidx = START_COLUMNS.get(prayer)
                if sidx is not None and sidx < len(row) and row[sidx].strip():
                    start = coerce_time(row[sidx].strip(), prayer=prayer.value)
                parsed_rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        start_time=start,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(row),
                            selector=f"table tr:nth-child({row_number})",
                        ),
                    )
                )

        if not parsed_rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=parsed_rows, warnings=warnings)
