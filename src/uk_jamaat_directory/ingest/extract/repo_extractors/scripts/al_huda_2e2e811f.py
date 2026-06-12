from __future__ import annotations

from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_day_of_month, parse_month_name
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
    key = "al_huda_2e2e811f"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("al-huda.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        year = datetime.now().year
        url = f"http://al-huda.org.uk/uploads/5/7/1/2/57121291/al_huda_timetable_{year}.pdf"
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
        rows: list[ExtractorRow] = []
        seen: set[tuple[date, str, int]] = set()
        prayer_label_map = {
            Prayer.FAJR: ["fajr"],
            Prayer.DHUHR: ["zuhr", "zohr", "ẓuhr"],
            Prayer.ASR: ["asr"],
            Prayer.MAGHRIB: ["maghrib"],
            Prayer.ISHA: ["esha", "isha", "ʿeshā", "eshā"],
        }
        for page_idx, page_tables in enumerate(pdf_helpers.extract_tables(artifact.body)):
            for raw_table in page_tables:
                cleaned = [[(cell or "").strip() for cell in row] for row in raw_table if row]
                if len(cleaned) < 5:
                    continue
                header_text = " ".join((c or "").lower() for c in cleaned[0] + cleaned[1])
                if "jamaa" not in header_text and "fajr" not in header_text:
                    continue
                # Locate the "Jamaa’ah Time" section header in row 0 to anchor jamaat columns
                jamaat_header_col: int | None = None
                for ci, c in enumerate(cleaned[0]):
                    if "jamaa" in (c or "").lower():
                        jamaat_header_col = ci
                        break
                row1 = cleaned[1] if len(cleaned) > 1 else []
                counts: dict[Prayer, list[int]] = {p: [] for p in prayer_label_map}
                for ci, cell in enumerate(row1):
                    cl = (cell or "").lower().replace("ʿ", "").replace("ṣ", "s").replace("ẓ", "z")
                    for p, kws in prayer_label_map.items():
                        if any(kw in cl for kw in kws):
                            counts[p].append(ci)
                jam_cols: dict[Prayer, int] = {}
                for p, idxs in counts.items():
                    candidates = [
                        i for i in idxs if jamaat_header_col is None or i >= jamaat_header_col
                    ]
                    if candidates:
                        jam_cols[p] = candidates[-1]
                    elif idxs:
                        jam_cols[p] = idxs[-1]
                if len(jam_cols) < 3:
                    # fall back to a known-good layout for older pages if detection is incomplete
                    jam_cols = {
                        Prayer.FAJR: 24,
                        Prayer.DHUHR: 27,
                        Prayer.ASR: 30,
                        Prayer.MAGHRIB: 33,
                        Prayer.ISHA: 36,
                    }
                year = datetime.now().year
                month = None
                for r in cleaned[:3]:
                    for cell in r:
                        mon = parse_month_name(cell)
                        if mon is not None:
                            month = mon
                            break
                    if month is not None:
                        break
                if month is None:
                    continue
                data_rows = [list(row) for row in cleaned[3:]]
                for col in jam_cols.values():
                    vals = list(
                        carry_forward(row[col] if col < len(row) else "" for row in data_rows)
                    )
                    for i, v in enumerate(vals):
                        if col < len(data_rows[i]):
                            data_rows[i][col] = v
                for r_idx, row in enumerate(data_rows):
                    day = None
                    for ci in range(min(6, len(row))):
                        dval = parse_day_of_month(row[ci])
                        if dval is not None:
                            day = dval
                            break
                    if day is None:
                        continue
                    try:
                        d = date(year, month, day)
                    except ValueError:
                        continue
                    for prayer, col in jam_cols.items():
                        if col >= len(row):
                            continue
                        raw = (row[col] or "").strip()
                        if not raw or raw in {'"', "''", "“", "”", "–", "-", ""}:
                            continue
                        low = raw.lower()
                        if any(
                            x in low for x in ("between", "will take", "note", "see ", "column")
                        ):
                            continue
                        norm = raw.replace(".", ":")
                        jamaat = coerce_time(norm, prayer=prayer.value)
                        if jamaat is None:
                            warnings.append(
                                ExtractorWarning(
                                    code="unparseable_time",
                                    message=f"{d} {prayer.value}: {raw!r}",
                                    target_label="timetable",
                                )
                            )
                            continue
                        window = PLAUSIBLE_WINDOWS.get(prayer.value)
                        if window and not (window[0] <= jamaat <= window[1]):
                            warnings.append(
                                ExtractorWarning(
                                    code="implausible_time",
                                    message=f"{d} {prayer.value}: {raw!r} outside plausible window",
                                    target_label="timetable",
                                )
                            )
                            continue
                        k = (d, prayer.value, 1)
                        if k in seen:
                            continue
                        seen.add(k)
                        rows.append(
                            ExtractorRow(
                                date=d,
                                prayer=prayer,
                                jamaat_time=jamaat,
                                timezone=ctx.timezone,
                                evidence=ctx.evidence(
                                    target_label="timetable",
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    raw_text=" | ".join(str(x) for x in row),
                                    selector=f"pdf page {page_idx} row {r_idx}",
                                ),
                            )
                        )
        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows in PDF",
            )
        return ExtractorResult(rows=rows, warnings=warnings)
