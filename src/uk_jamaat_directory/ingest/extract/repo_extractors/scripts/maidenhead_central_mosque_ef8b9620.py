from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import (
    dates_for_month,
    parse_day_month,
)
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

IQAMAH_HEADER_TOKENS = frozenset({"date", "fajr", "dhuhr", "asr", "maghrib", "isha"})

PRAYER_COL_MAP = [
    (1, Prayer.FAJR),
    (2, Prayer.DHUHR),
    (3, Prayer.ASR),
    (4, Prayer.MAGHRIB),
    (5, Prayer.ISHA),
]


class Extractor(BaseMosqueWebsiteExtractor):
    key = "maidenhead_central_mosque_ef8b9620"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("maidenheadmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://timing.athanplus.com/masjid/widgets/monthly?theme=1&masjid_id=4KB01PA5",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no tables found in HTML",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no tables found",
            )

        all_rows = tables[0].rows
        warnings: list[ExtractorWarning] = []

        iqamah_header_idx = None
        for idx, row in enumerate(all_rows):
            tokens = frozenset(cell.strip().lower() for cell in row if cell.strip())
            if tokens == IQAMAH_HEADER_TOKENS:
                iqamah_header_idx = idx
                break

        if iqamah_header_idx is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_iqamah_table",
                        message="iqamah timetable not found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="iqamah table not found",
            )

        year = datetime.now().year
        iqamah_sparse: list[tuple[datetime.date, list[str]]] = []

        for idx in range(iqamah_header_idx + 1, len(all_rows)):
            row = all_rows[idx]
            cells = [c.strip() for c in row if c.strip()]
            if len(cells) < 6:
                break
            raw_date = cells[0]
            row_date = parse_day_month(raw_date, year=year)
            if row_date is None:
                warnings.append(
                    ExtractorWarning(
                        code="bad_date",
                        message=f"could not parse iqamah date {raw_date!r}",
                        target_label="timetable",
                    )
                )
                break
            iqamah_sparse.append((row_date, cells))

        if not iqamah_sparse:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no iqamah rows found",
            )

        month = iqamah_sparse[0][0].month

        jumuah_times: list[str] = []
        for idx in range(iqamah_header_idx + 1, len(all_rows)):
            row = all_rows[idx]
            joined = " ".join(c.strip().lower() for c in row if c.strip())
            if "jumu" in joined:
                next_row = all_rows[idx + 1] if idx + 1 < len(all_rows) else []
                jumuah_times = [t.strip() for t in next_row if t.strip() and ":" in t.strip()]
                break

        all_dates = dates_for_month(year, month)
        parsed_rows: list[ExtractorRow] = []
        current_times: list[str] = []

        for row_date in all_dates:
            for sd, cells in iqamah_sparse:
                if sd <= row_date:
                    current_times = cells

            if not current_times:
                continue

            is_friday = row_date.weekday() == 4

            for col_idx, prayer in PRAYER_COL_MAP:
                if col_idx >= len(current_times):
                    continue
                raw = current_times[col_idx]
                if raw.lower() in ("sunset", ""):
                    continue

                if prayer == Prayer.DHUHR and is_friday:
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

                parsed_rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        start_time=None,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{prayer.value}: {raw}",
                            derivation={"method": "iqamah table row"},
                        ),
                        session_number=1,
                    )
                )

            if is_friday and jumuah_times:
                for session_num, raw_t in enumerate(jumuah_times, start=1):
                    jamaat = coerce_time(raw_t, prayer=Prayer.DHUHR.value)
                    if jamaat is None:
                        warnings.append(
                            ExtractorWarning(
                                code="unparseable_jumuah",
                                message=f"{row_date} jumuah session {session_num}: {raw_t!r}",
                                target_label="timetable",
                            )
                        )
                        continue
                    parsed_rows.append(
                        ExtractorRow(
                            date=row_date,
                            prayer=Prayer.DHUHR,
                            jamaat_time=jamaat,
                            start_time=None,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"jumuah session {session_num}: {raw_t}",
                                derivation={"method": "jumuah table row"},
                            ),
                            session_number=session_num,
                            session_label=f"Jumu'ah {session_num}",
                        )
                    )

        if not parsed_rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )

        return ExtractorResult(rows=parsed_rows, warnings=warnings)
