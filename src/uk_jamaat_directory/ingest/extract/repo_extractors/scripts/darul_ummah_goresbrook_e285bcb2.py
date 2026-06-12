from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
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
    key = "darul_ummah_goresbrook_e285bcb2"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("darulummahgoresbrook.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://darulummahgoresbrook.org.uk/prayer-times/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        tables = html_helpers.extract_tables(html)
        dpt_table = None
        for tbl in tables:
            for r in tbl.rows:
                if html_helpers.header_matches(r, ["prayer", "fajr"]):
                    dpt_table = tbl
                    break
            if dpt_table is not None:
                break

        if dpt_table is None:
            if "dptTimetable" not in html:
                return ExtractorResult(rows=[], no_schedule_reason="no timetable table found")

        row_date = datetime.now().date()

        jama_values: list[str] = []
        prayer_labels: list[str] = []

        if dpt_table is not None:
            prayer_header_row: list[str] | None = None
            jama_row: list[str] | None = None
            for i, r in enumerate(dpt_table.rows):
                if html_helpers.header_matches(r, ["prayer", "fajr"]):
                    prayer_header_row = r
                    if i + 2 < len(dpt_table.rows):
                        cand = dpt_table.rows[i + 2]
                        if "jama" in (cand[0] or "").lower():
                            jama_row = cand
                    if jama_row is None and i + 1 < len(dpt_table.rows):
                        cand = dpt_table.rows[i + 1]
                        if "jama" in (cand[0] or "").lower():
                            jama_row = cand
                    break

            if prayer_header_row and jama_row:
                prayer_labels = [c.strip() for c in prayer_header_row[1:]]
                raw_jama = [c.strip() for c in jama_row[1:]]
                jama_idx = 0
                for lab in prayer_labels:
                    l = lab.lower()
                    if "sunrise" in l or "dhuha" in l:
                        continue
                    if jama_idx < len(raw_jama):
                        jama_values.append(raw_jama[jama_idx])
                        jama_idx += 1

        if not jama_values:
            jama_cells = re.findall(
                r'<td[^>]*class=["\']?(?:jamah|highlight)["\']?[^>]*>([^<]+)</td>',
                html,
                re.IGNORECASE,
            )
            for v in jama_cells:
                v = v.strip()
                if re.search(r"\d", v) and ":" in v:
                    jama_values.append(v)
            seen = set()
            uniq = []
            for v in jama_values:
                if v not in seen:
                    seen.add(v)
                    uniq.append(v)
            jama_values = uniq[:5]

            if not prayer_labels:
                hdr = re.search(
                    r"<tr[^>]*>\s*<th[^>]*>Prayer</th>.*?<th[^>]*>([^<]+)</th>.*?<th[^>]*>([^<]+)</th>.*?<th[^>]*>([^<]+)</th>.*?<th[^>]*>([^<]+)</th>.*?<th[^>]*>([^<]+)</th>.*?<th[^>]*>([^<]+)</th>",
                    html,
                    re.IGNORECASE | re.DOTALL,
                )
                if hdr:
                    prayer_labels = [
                        hdr.group(1),
                        "Sunrise",
                        hdr.group(3),
                        hdr.group(4),
                        hdr.group(5),
                        hdr.group(6),
                    ]

        paired: list[tuple[Prayer, str]] = []
        jv_idx = 0
        for lab in prayer_labels or ["Fajr", "Sunrise", "Jumuah", "Asr", "Maghrib", "Isha"]:
            l = lab.lower()
            if "sunrise" in l or "dhuha" in l:
                continue
            if jv_idx >= len(jama_values):
                break
            pr = parse_prayer_label(lab)
            if pr is not None:
                paired.append((pr, jama_values[jv_idx]))
            jv_idx += 1

        for prayer, iqamah in paired:
            iq = iqamah.strip()
            jamaat = coerce_time(iq, prayer=prayer.value)
            if jamaat is None:
                continue
            window = PLAUSIBLE_WINDOWS.get(prayer.value)
            if window and not (window[0] <= jamaat <= window[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"{row_date} {prayer.value}: {iq!r} outside plausible window",
                        target_label="timetable",
                    )
                )
                continue

            rows.append(
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
                        raw_text=f"{prayer.value} | {iq}",
                        selector="dptTimetable jama'ah row",
                    ),
                )
            )

        if not rows:
            iqamahs_lower = [v.strip().lower() for v in jama_values]
            if iqamahs_lower and all(i.startswith("12:00") for i in iqamahs_lower):
                return ExtractorResult(rows=[], no_schedule_reason="pdf target — awaiting parser")
            return ExtractorResult(rows=[], no_schedule_reason="no extractable rows")

        order = {
            Prayer.FAJR: 0,
            Prayer.DHUHR: 1,
            Prayer.ASR: 2,
            Prayer.MAGHRIB: 3,
            Prayer.ISHA: 4,
            Prayer.JUMUAH: 5,
        }
        rows.sort(key=lambda r: (r.date, order.get(r.prayer, 999), r.session_number))

        return ExtractorResult(rows=rows, warnings=warnings)
