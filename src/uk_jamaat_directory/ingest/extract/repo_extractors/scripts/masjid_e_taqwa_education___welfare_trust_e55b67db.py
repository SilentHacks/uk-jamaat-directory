from __future__ import annotations

from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_day_of_month
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
    key = "masjid_e_taqwa_education___welfare_trust_e55b67db"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("masjidetaqwa.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        year = datetime.now().year
        url = f"https://www.masjidetaqwa.co.uk/downloads/Taqwa{year}.pdf"
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

        rows_out: list[ExtractorRow] = []
        year = datetime.now().year
        MONTHS = {
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }
        PRAYER_ORDER = [Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA]

        for page_idx, page_tables in enumerate(page_tables):
            for raw_table in page_tables:
                if not raw_table:
                    continue
                cleaned = [
                    [(cell or "").strip() for cell in row]
                    for row in raw_table
                    if any((c or "").strip() for c in row)
                ]
                if len(cleaned) < 4:
                    continue

                header_idx = None
                for i, row in enumerate(cleaned[:6]):
                    ups = [c.upper() for c in row]
                    if any("JAMMAT" in c or "JAMAT" in c for c in ups):
                        header_idx = i
                        break
                if header_idx is None:
                    continue

                header = cleaned[header_idx]
                jcols = [i for i, c in enumerate(header) if "JAMMAT" in c.upper()]
                if len(jcols) < 5:
                    continue

                jam_cols_map = {
                    PRAYER_ORDER[0]: jcols[0],
                    PRAYER_ORDER[1]: jcols[1],
                    PRAYER_ORDER[2]: jcols[2],
                    PRAYER_ORDER[3]: jcols[3],
                    PRAYER_ORDER[4]: jcols[4],
                }

                page_month = None
                for r in cleaned[:3]:
                    for cell in r:
                        cl = cell.lower().replace("-", " ")
                        for mname, mnum in MONTHS.items():
                            if mname in cl:
                                page_month = mnum
                                break
                        if page_month:
                            break
                    if page_month:
                        break
                if page_month is None:
                    for r in cleaned[:2]:
                        for cell in r:
                            parts = cell.split("-")
                            if len(parts) == 2 and parts[0].lower()[:3] in MONTHS:
                                page_month = MONTHS[parts[0].lower()[:3]]
                                break
                        if page_month:
                            break
                if page_month is None:
                    page_month = datetime.now().month

                for r_idx, row in enumerate(cleaned[header_idx + 1 :], start=header_idx + 1):
                    day_str = ""
                    for cand in (1, 0, 2, 3):
                        if cand < len(row) and row[cand].isdigit():
                            day_str = row[cand]
                            break
                    if not day_str:
                        for c in row[:5]:
                            if c.isdigit():
                                day_str = c
                                break
                    day = parse_day_of_month(day_str) if day_str else None
                    if day is None:
                        continue
                    try:
                        d = date(year, page_month, day)
                    except ValueError:
                        continue

                    is_fri = d.weekday() == 4

                    for prayer, jcol in jam_cols_map.items():
                        if jcol >= len(row):
                            continue
                        raw = row[jcol].strip()
                        if not raw or not any(ch.isdigit() for ch in raw):
                            continue
                        use_prayer = prayer
                        sess = 1
                        sess_label = None
                        if prayer == Prayer.DHUHR and is_fri:
                            use_prayer = Prayer.JUMUAH
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
                        rows_out.append(
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
                                    selector=f"page {page_idx} row {r_idx}",
                                ),
                            )
                        )

        if not rows_out:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )

        order = {
            Prayer.FAJR: 0,
            Prayer.DHUHR: 1,
            Prayer.ASR: 2,
            Prayer.MAGHRIB: 3,
            Prayer.ISHA: 4,
            Prayer.JUMUAH: 5,
        }
        rows_out.sort(key=lambda r: (r.date, order.get(r.prayer, 99), r.session_number))
        return ExtractorResult(rows=rows_out, warnings=warnings)
