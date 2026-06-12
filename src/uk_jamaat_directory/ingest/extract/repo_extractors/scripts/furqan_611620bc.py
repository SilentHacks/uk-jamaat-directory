from __future__ import annotations

from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_day_of_month
from uk_jamaat_directory.ingest.extract.helpers.rows import carry_forward
from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS, coerce_time
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
    key = "furqan_611620bc"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("madrasahalfurqan.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        month_name = now.strftime("%B").upper()
        dir_year = now.year
        dir_month = now.month - 2
        if dir_month < 1:
            dir_month += 12
            dir_year -= 1
        url = (
            f"https://madrasahalfurqan.co.uk/wp-content/uploads/"
            f"{dir_year}/{dir_month:02d}/Masjid-Al-Furqan-TIMETABLE-{month_name}-{now.year}.pdf"
        )
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
        if not artifact.body:
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

        header_idx = None
        for i, row in enumerate(cleaned):
            lower = [c.lower() for c in row]
            if any("fajr" in c for c in lower) and any("zuhr" in c for c in lower):
                header_idx = i
                break
        if header_idx is None:
            for i, row in enumerate(cleaned):
                lower = [c.lower() for c in row]
                if any("date" in c for c in lower) and any("fajr" in c for c in lower):
                    header_idx = i
                    break
        if header_idx is None:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="timetable table not found in PDF",
            )

        header = cleaned[header_idx]
        data_rows = cleaned[header_idx + 1 :]

        def col_for(needle: str, *, rightmost: bool = False) -> int | None:
            n = needle.lower()
            matches = [idx for idx, cell in enumerate(header) if n in cell.lower()]
            if not matches:
                return None
            return matches[-1] if rightmost else matches[0]

        col_date = col_for("date", rightmost=True)
        col_fajr = col_for("fajr", rightmost=True)
        col_zuhr = col_for("zuhr", rightmost=True)
        col_asr = col_for("asr", rightmost=True)
        col_maghrib = col_for("maghrib", rightmost=True)
        col_isha = col_for("ishaa", rightmost=True) or col_for("isha", rightmost=True)

        prayer_col_map: dict[Prayer, int] = {}
        if col_fajr is not None:
            prayer_col_map[Prayer.FAJR] = col_fajr
        if col_zuhr is not None:
            prayer_col_map[Prayer.DHUHR] = col_zuhr
        if col_asr is not None:
            prayer_col_map[Prayer.ASR] = col_asr
        if col_maghrib is not None:
            prayer_col_map[Prayer.MAGHRIB] = col_maghrib
        if col_isha is not None:
            prayer_col_map[Prayer.ISHA] = col_isha

        if not prayer_col_map or col_date is None:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no prayer columns found"
            )

        year = datetime.now().year
        month = datetime.now().month

        parsed: list[tuple[date, dict[Prayer, str]]] = []
        for r in data_rows:
            if col_date >= len(r):
                continue
            day_str = r[col_date]
            day = parse_day_of_month(day_str)
            if day is None:
                continue
            try:
                d = date(year, month, day)
            except ValueError:
                continue
            times: dict[Prayer, str] = {}
            for pr, cidx in prayer_col_map.items():
                if cidx < len(r):
                    val = r[cidx].strip()
                    if val:
                        times[pr] = val
            if times:
                parsed.append((d, times))

        if not parsed:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )

        days_sorted = [p[0] for p in parsed]
        per_prayer_raw: dict[Prayer, list[str]] = {p: [] for p in prayer_col_map}
        for d, tmap in parsed:
            for p in per_prayer_raw:
                per_prayer_raw[p].append(tmap.get(p, ""))
        per_prayer_carried = {p: carry_forward(vals) for p, vals in per_prayer_raw.items()}

        rows: list[ExtractorRow] = []
        for i, (d, _) in enumerate(parsed):
            for prayer, carried_list in per_prayer_carried.items():
                raw = carried_list[i] if i < len(carried_list) else ""
                if not raw:
                    continue
                use_prayer = prayer
                sess = 1
                sess_label: str | None = None
                if prayer == Prayer.DHUHR and d.weekday() == 4:
                    use_prayer = Prayer.JUMUAH
                    sess_label = "Jumuah"
                jt = coerce_time(raw, prayer=use_prayer.value)
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{d} {use_prayer.value}: {raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                window = PLAUSIBLE_WINDOWS.get(use_prayer.value)
                if window and not (window[0] <= jt <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{d} {use_prayer.value}: {raw!r} outside plausible window",
                            target_label="timetable",
                        )
                    )
                    continue
                rows.append(
                    ExtractorRow(
                        date=d,
                        prayer=use_prayer,
                        jamaat_time=jt,
                        session_number=sess,
                        session_label=sess_label,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=raw,
                            selector=f"pdf row {i}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
