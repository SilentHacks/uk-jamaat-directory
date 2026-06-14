from __future__ import annotations

import re
from datetime import date, datetime, time

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_day_of_month, parse_month_name
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


class Extractor(BaseMosqueWebsiteExtractor):
    key = "paigham_e_islam_trust_a745cd50"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("paigham-e-islam.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # The site publishes a monthly PDF timetable (linked from / and /prayer-times.php).
        # No HTML table of jamaat times is present; the schedule is delivered as PDF.
        # Target the current month's PDF using the site's naming pattern.
        now = datetime.now()
        month_abbr = now.strftime("%b")
        url = f"http://paigham-e-islam.co.uk/resources/Timetable%20{month_abbr}%20{now.year}.pdf"
        self.targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        warnings: list[ExtractorWarning] = []
        try:
            page_tables = pdf_helpers.extract_tables(artifact.body)
        except Exception:
            return ExtractorResult(rows=[], no_schedule_reason="failed to parse PDF tables")

        if not page_tables or not page_tables[0]:
            return ExtractorResult(rows=[], no_schedule_reason="no tables found in PDF")

        raw_table = page_tables[0][0]
        cleaned = [
            [(cell or "").strip() for cell in row]
            for row in raw_table
            if any((c or "").strip() for c in row)
        ]
        if len(cleaned) < 3:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="timetable table not found in PDF",
            )

        # header row is the one starting with DATE
        header_idx = None
        for i, row in enumerate(cleaned):
            if row and (row[0] or "").upper() == "DATE":
                header_idx = i
                break
        if header_idx is None or header_idx + 1 >= len(cleaned):
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="timetable table not found in PDF",
            )
        data_rows = cleaned[header_idx + 1 :]

        # column indices for JAMAT values (0-based, from fixed layout)
        COL_FAJR_J = 4
        COL_ZUHR_J = 7
        COL_ASR_J = 9
        COL_MAGH_J = 10
        COL_ISHA_J = 12
        jamaat_col_indices = (COL_FAJR_J, COL_ZUHR_J, COL_ASR_J, COL_MAGH_J, COL_ISHA_J)

        # Expand batched physical rows (cells contain \n-separated values for consecutive days)
        atomic_rows: list[list[str]] = []
        for r in data_rows:
            splits: list[list[str]] = []
            max_n = 1
            for cell in r:
                parts = [p.strip() for p in cell.split("\n") if p.strip()]
                splits.append(parts)
                if len(parts) > max_n:
                    max_n = len(parts)
            if max_n == 0:
                continue
            for j, parts in enumerate(splits):
                if len(parts) < max_n:
                    last = parts[-1] if parts else ""
                    splits[j] = parts + [last] * (max_n - len(parts))
            for k in range(max_n):
                atomic = [splits[j][k] if k < len(splits[j]) else "" for j in range(len(r))]
                atomic_rows.append(atomic)

        # build per-day expanded with raw jamaat strings (still containing " carry markers)
        TIME_LIKE = re.compile(r"^\d{1,2}[:.]\d{2}")
        expanded: list[tuple[int, list[str]]] = []
        for ar in atomic_rows:
            if len(ar) <= COL_ISHA_J:
                continue
            dayn = parse_day_of_month(ar[0])
            if dayn is None:
                continue
            raw5: list[str] = []
            for cidx in jamaat_col_indices:
                val = (ar[cidx] if cidx < len(ar) else "").strip()
                # drop intruding jumuah text or non-time carry markers from other columns
                if val and not TIME_LIKE.match(val):
                    val = ""
                raw5.append(val)
            expanded.append((dayn, raw5))

        if not expanded:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )

        # carry forward within each jamaat column
        col_raws: list[list[str]] = [[] for _ in range(5)]
        for _, r5 in expanded:
            for c in range(5):
                col_raws[c].append(r5[c])
        carried = [carry_forward(cr) for cr in col_raws]

        # determine year/month; prefer from PDF header text
        year = datetime.now().year
        month = datetime.now().month
        full_text = pdf_helpers.extract_text(artifact.body) or ""
        for m in re.finditer(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
            full_text,
            re.IGNORECASE,
        ):
            mon = parse_month_name(m.group(1))
            if mon is not None:
                month = mon
                year = int(m.group(2))
                break

        PRAYERS = [Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA]
        jamaat_rows: list[ExtractorRow] = []
        for i, (dayn, _) in enumerate(expanded):
            try:
                rd = date(year, month, dayn)
            except ValueError:
                continue
            is_fri = rd.weekday() == 4
            for pi, prayer in enumerate(PRAYERS):
                raw = carried[pi][i] if i < len(carried[pi]) else ""
                if not raw:
                    continue
                if is_fri and prayer == Prayer.DHUHR:
                    continue  # dhuhr replaced by jumuah on Fridays
                jt = coerce_time(raw, prayer=prayer.value)
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{rd} {prayer.value}: {raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                jamaat_rows.append(
                    ExtractorRow(
                        date=rd,
                        prayer=prayer,
                        jamaat_time=jt,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=raw,
                            selector=f"day {dayn}",
                        ),
                    )
                )

        # Jumuah sessions (always from footer text on this timetable)
        jumuah_raw_list: list[str] = []
        for m in re.finditer(
            r"(?i)(?:first|second)\s+juma\s*jamat\s*([0-9]{1,2}[:.][0-9]{2})", full_text
        ):
            jumuah_raw_list.append(m.group(1))
        if len(jumuah_raw_list) < 2:
            for m in re.finditer(r"(?i)juma[^0-9]*([0-9]{1,2}[:.][0-9]{2})", full_text):
                val = m.group(1)
                if val not in jumuah_raw_list:
                    jumuah_raw_list.append(val)
                if len(jumuah_raw_list) >= 2:
                    break

        jumuah_entries: list[tuple[int, str, time | None]] = []
        for idx, rawj in enumerate(jumuah_raw_list[:2], 1):
            jt = coerce_time(rawj, prayer="jumuah")
            jumuah_entries.append((idx, rawj, jt))

        fri_dates = sorted({r.date for r in jamaat_rows if r.date.weekday() == 4})
        for fd in fri_dates:
            for sess, rawj, jt in jumuah_entries:
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_jumuah",
                            message=f"{fd} jumuah {sess}: {rawj!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                jamaat_rows.append(
                    ExtractorRow(
                        date=fd,
                        prayer=Prayer.JUMUAH,
                        jamaat_time=jt,
                        session_number=sess,
                        session_label=f"Jumuah {sess}",
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=rawj,
                            selector=f"jumuah footer session {sess}",
                            derivation={"note": "from first/second juma jamat in PDF footer"},
                        ),
                    )
                )

        rows = jamaat_rows
        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=rows, warnings=warnings)
