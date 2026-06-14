from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_day_month
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
    key = "edgware_road_mosque_79e0eae2"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("edgwareroadmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://timing.athanplus.com/masjid/widgets/monthly?theme=1&masjid_id=3AOb63Le",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
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

        all_rows_by_table = [t.rows for t in tables]
        warnings: list[ExtractorWarning] = []

        # Find the IQAMAH table header row
        iqamah_header_idx = None
        iqamah_table_rows = None
        for tbl_rows in all_rows_by_table:
            for idx, row in enumerate(tbl_rows):
                tokens = frozenset(cell.strip().lower() for cell in row if cell.strip())
                if tokens == IQAMAH_HEADER_TOKENS:
                    iqamah_header_idx = idx
                    iqamah_table_rows = tbl_rows
                    break
            if iqamah_header_idx is not None:
                break

        if iqamah_header_idx is None or iqamah_table_rows is None:
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

        for idx in range(iqamah_header_idx + 1, len(iqamah_table_rows)):
            row = iqamah_table_rows[idx]
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

        # Extract Jumu'ah times from the jumuah-table (two sessions, constant for the view)
        jumuah_times: list[str] = []
        for tbl_rows in all_rows_by_table:
            for ridx, row in enumerate(tbl_rows):
                joined = " ".join(c.strip().lower() for c in row if c.strip())
                if "jumu" in joined:
                    # Collect time-like cells in this and following rows (up to a few)
                    for r2 in tbl_rows[ridx : ridx + 6]:
                        for cell in r2:
                            cl = cell.strip()
                            if not cl:
                                continue
                            # match H:MM or H:MM AM/PM
                            if coerce_time(cl) is not None:
                                if cl not in jumuah_times:
                                    jumuah_times.append(cl)
                    if len(jumuah_times) >= 2:
                        break
            if len(jumuah_times) >= 2:
                break

        parsed_rows: list[ExtractorRow] = []

        for row_date, cells in iqamah_sparse:
            is_friday = row_date.weekday() == 4

            for col_idx, prayer in PRAYER_COL_MAP:
                if col_idx >= len(cells):
                    continue
                raw = cells[col_idx]
                if not raw or raw.lower() in ("sunset", ""):
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

            # Jumu'ah sessions on Fridays (use Prayer.JUMUAH)
            if is_friday and jumuah_times:
                for session_num, raw_t in enumerate(jumuah_times[:2], start=1):
                    jt = coerce_time(raw_t, prayer=Prayer.JUMUAH.value)
                    if jt is None:
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
                            prayer=Prayer.JUMUAH,
                            jamaat_time=jt,
                            start_time=None,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"jumuah session {session_num}: {raw_t}",
                                derivation={"method": "jumuah table"},
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
