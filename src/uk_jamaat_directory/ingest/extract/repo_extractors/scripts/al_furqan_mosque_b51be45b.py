from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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


def _extract_cells(row_html: str) -> list[str]:
    cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.IGNORECASE | re.DOTALL)
    return [re.sub(r"<[^>]+>", "", c).strip() for c in cells]


class Extractor(BaseMosqueWebsiteExtractor):
    key = "al_furqan_mosque_b51be45b"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("alfurqanllm.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        url = (
            "https://alfurqanllm.org/wp-admin/admin-ajax.php"
            f"?action=get_monthly_timetable&month={now.month}&year={now.year}"
        )
        self.targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.HTML,
            ),
        )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        warnings: list[ExtractorWarning] = []
        rows_out: list[ExtractorRow] = []

        year = datetime.now().year

        # Known column indices for Iqamah (0-based) in the dpt monthly table:
        # [0]=Date, [1]=Day, [2]=FajrBeg, [3]=FajrIq, [4]=Sunrise,
        # [5]=ZuhrBeg, [6]=ZuhrIq, [7]=AsrStd, [8]=AsrHan, [9]=AsrIq,
        # [10]=MaghBeg, [11]=MaghIq, [12]=IshaBeg, [13]=IshaIq
        jam_map = {
            Prayer.FAJR: 3,
            Prayer.DHUHR: 6,
            Prayer.ASR: 9,
            Prayer.MAGHRIB: 11,
            Prayer.ISHA: 13,
        }

        # Scan the entire fragment for <tr>...</tr> (works even if table tags are unbalanced or missing in the AJAX response)
        trs = re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", html)
        parsed_rows: list[list[str]] = []
        for tr in trs:
            cells = _extract_cells(tr)
            if any(cells):
                parsed_rows.append(cells)

        # If we got rows that look like header + data, skip a header row
        start_idx = 0
        if parsed_rows:
            first_low = [c.lower() for c in parsed_rows[0]]
            if any("date" in c for c in first_low) or any("iqamah" in c for c in first_low):
                start_idx = 1

        for r in parsed_rows[start_idx:]:
            if not r or len(r) < 5:
                continue
            ds = r[0]
            d = parse_date_flexible(ds, default_year=year)
            if d is None:
                continue
            # Force to current year (source may echo a stale year in the label)
            if d.year != year:
                try:
                    d = d.replace(year=year)
                except ValueError:
                    continue
            for pr, ci in jam_map.items():
                if ci >= len(r):
                    continue
                raw = (r[ci] or "").strip()
                if not raw:
                    continue
                jt = coerce_time(raw, prayer=pr.value)
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{d} {pr.value}: {raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                win = PLAUSIBLE_WINDOWS.get(pr.value)
                if win and not (win[0] <= jt <= win[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{d} {pr.value}: {raw!r} outside plausible window",
                            target_label="timetable",
                        )
                    )
                    continue
                rows_out.append(
                    ExtractorRow(
                        date=d,
                        prayer=pr,
                        jamaat_time=jt,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(r),
                            selector="dpt ajax row",
                        ),
                    )
                )

        if not rows_out:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=rows_out, warnings=warnings)
