from __future__ import annotations

import re
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
    key = "masjid_e_aisha_53fc614f"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("masjidaisha.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://masjidaisha.co.uk/download/june-july-2026-timetable/?wpdmdl=377",
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

        def _find_month_year(text: str) -> tuple[int, int]:
            year = datetime.now().year
            month = datetime.now().month
            # PDF text extraction often inserts spaces inside words (layout artifacts): "J ULY", "202 6"
            compact = re.sub(r"\s+", "", text)
            my = re.search(r"(20\d{2})", compact)
            if my:
                ys = my.group(1)
                if ys.startswith("20"):
                    year = int(ys)
            mname = re.search(
                r"(January|February|March|April|May|June|July|August|September|October|November|December)",
                compact,
                re.IGNORECASE,
            )
            if mname:
                mon = parse_month_name(mname.group(1))
                if mon is not None:
                    month = mon
            return year, month

        JAM_COLS: dict[Prayer, int] = {
            Prayer.FAJR: 9,
            Prayer.DHUHR: 10,
            Prayer.ASR: 11,
            Prayer.MAGHRIB: 12,
            Prayer.ISHA: 13,
        }
        DATE_COL = 1

        for page_idx, page_tables in enumerate(pdf_helpers.extract_tables(artifact.body)):
            for raw_table in page_tables:
                cleaned = [[(cell or "").strip() for cell in row] for row in raw_table if row]
                if len(cleaned) < 3:
                    continue
                h1 = " ".join((c or "").lower() for c in cleaned[1])
                if "fajar" not in h1 and "zuhr" not in h1:
                    continue
                y, m = _find_month_year(" ".join(str(c or "") for c in cleaned[0] + cleaned[1]))
                data_rows = cleaned[2:]
                # carry forward repeated jamaat markers shown as quotes
                for col in JAM_COLS.values():
                    vals = list(
                        carry_forward(row[col] if col < len(row) else "" for row in data_rows)
                    )
                    for i, v in enumerate(vals):
                        if col < len(data_rows[i]):
                            data_rows[i][col] = v
                for r_idx, row in enumerate(data_rows):
                    if not row or not row[DATE_COL]:
                        continue
                    day_num = parse_day_of_month(row[DATE_COL])
                    if day_num is None:
                        continue
                    try:
                        d = date(y, m, day_num)
                    except ValueError:
                        continue
                    for prayer, col in JAM_COLS.items():
                        if col >= len(row):
                            continue
                        raw = (row[col] or "").strip()
                        if not raw or raw in {'"', "''", "“", "”", "–", "-", ""}:
                            continue
                        jamaat = coerce_time(raw, prayer=prayer.value)
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
