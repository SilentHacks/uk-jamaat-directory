from __future__ import annotations

import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
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
    key = "masjid_taqw_86938208"
    version = "2026.06.12.4"
    source_match = SourceMatch(domains=("masjidtaqwa.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        year = now.year
        month_num = now.month
        month_name = now.strftime("%B")
        url = (
            "https://masjidtaqwa.co.uk/onewebmedia/"
            f"Masjid%20Taqwa%20Salaah%20Timetables%20{year}-{month_num:02d}-{month_name}-A4.pdf"
        )
        self._targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        warnings: list[ExtractorWarning] = []
        rows_out: list[ExtractorRow] = []

        # --- Try tolerant text-based extraction first (handles NBSP, carry markers) ---
        text = pdf_helpers.extract_text(artifact.body)
        if text and len(text.strip()) >= 50:
            year = datetime.now().year
            month = datetime.now().month
            m = re.search(
                r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b",
                text,
                re.IGNORECASE,
            )
            if m:
                mon_name = m.group(1)
                year = int(m.group(2))
                mon_map = {
                    "january": 1,
                    "february": 2,
                    "march": 3,
                    "april": 4,
                    "may": 5,
                    "june": 6,
                    "july": 7,
                    "august": 8,
                    "september": 9,
                    "october": 10,
                    "november": 11,
                    "december": 12,
                }
                month = mon_map.get(mon_name.lower(), month)

            CARRY = "CARRY"
            CARRY_PAT = re.compile(r"^[“\"”″']+$")

            def norm_ws(s: str) -> str:
                return re.sub(r"[\u00a0\u202f\u2009\s]+", " ", s)

            def collect_time_tokens(line: str) -> list[str]:
                out: list[str] = []
                for raw in norm_ws(line).split():
                    t = raw.strip()
                    if not t:
                        continue
                    if CARRY_PAT.match(t):
                        out.append(CARRY)
                        continue
                    if re.match(r"^\d{1,2}:\d{2}$", t):
                        out.append(t)
                return out

            # Accept lines that begin with a 1-2 digit day number followed by non-digit (handles NBSPs)
            dayish = re.compile(r"^\s*(\d{1,2})\D")

            JAMAT_IDXS = {
                Prayer.FAJR: 1,
                Prayer.DHUHR: 4,
                Prayer.ASR: 6,
                Prayer.MAGHRIB: 8,
                Prayer.ISHA: 10,
            }

            last: dict[Prayer, str | None] = {
                Prayer.FAJR: None,
                Prayer.DHUHR: None,
                Prayer.ASR: None,
                Prayer.MAGHRIB: None,
                Prayer.ISHA: None,
            }

            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                dm = dayish.match(line)
                if not dm:
                    continue
                try:
                    day = int(dm.group(1))
                except ValueError:
                    continue
                if not (1 <= day <= 31):
                    continue
                try:
                    d = date(year, month, day)
                except ValueError:
                    continue

                toks = collect_time_tokens(line)
                if len(toks) < 5:
                    pass  # may still resolve via last-seen carries

                def pick(prayer: Prayer) -> str | None:
                    idx = JAMAT_IDXS[prayer]
                    if idx >= len(toks):
                        return last[prayer]
                    v = toks[idx]
                    if v == CARRY:
                        return last[prayer]
                    last[prayer] = v
                    return v

                jamat_raw = {
                    Prayer.FAJR: pick(Prayer.FAJR),
                    Prayer.DHUHR: pick(Prayer.DHUHR),
                    Prayer.ASR: pick(Prayer.ASR),
                    Prayer.MAGHRIB: pick(Prayer.MAGHRIB),
                    Prayer.ISHA: pick(Prayer.ISHA),
                }

                is_fri = d.weekday() == 4

                for prayer, raw in jamat_raw.items():
                    if not raw:
                        continue
                    use_prayer = Prayer.JUMUAH if (prayer is Prayer.DHUHR and is_fri) else prayer
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
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=line[:200],
                                selector=f"day {day}",
                            ),
                        )
                    )

        # --- Fallback to table extraction if text path produced nothing ---
        if not rows_out:
            try:
                page_tables = pdf_helpers.extract_tables(artifact.body)
            except Exception:
                page_tables = []
            for page_idx, page in enumerate(page_tables):
                for raw_table in page:
                    if not raw_table:
                        continue
                    cleaned = [[(cell or "").strip() for cell in row] for row in raw_table if row]
                    if not cleaned:
                        continue
                    # Map columns from observed layout (no header row in the extracted rows):
                    # indices after clean: 0=dom,1=dow,2=hijri,3=fs,4=fj,5=sr,6=zs,7=zj,8=as,9=aj,10=ss,11=ms,12=is,13=ij
                    # We only have a few rows surfaced by the extractor; still real jamaat values.
                    # Determine year/month from header text in the whole PDF text if possible.
                    year = datetime.now().year
                    month = datetime.now().month
                    if text:
                        m = re.search(
                            r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b",
                            text,
                            re.IGNORECASE,
                        )
                        if m:
                            mon_name = m.group(1)
                            year = int(m.group(2))
                            mon_map = {
                                "january": 1,
                                "february": 2,
                                "march": 3,
                                "april": 4,
                                "may": 5,
                                "june": 6,
                                "july": 7,
                                "august": 8,
                                "september": 9,
                                "october": 10,
                                "november": 11,
                                "december": 12,
                            }
                            month = mon_map.get(mon_name.lower(), month)

                    for r_idx, row in enumerate(cleaned):
                        if len(row) < 14:
                            continue
                        day_str = row[0]
                        try:
                            day = int(day_str)
                        except Exception:
                            continue
                        if not (1 <= day <= 31):
                            continue
                        try:
                            d = date(year, month, day)
                        except ValueError:
                            continue

                        raw_map = {
                            Prayer.FAJR: row[4],
                            Prayer.DHUHR: row[7],
                            Prayer.ASR: row[9],
                            Prayer.MAGHRIB: row[11],
                            Prayer.ISHA: row[13],
                        }

                        is_fri = d.weekday() == 4
                        for prayer, raw in raw_map.items():
                            if not raw or not any(ch.isdigit() for ch in raw):
                                continue
                            use_prayer = (
                                Prayer.JUMUAH if (prayer is Prayer.DHUHR and is_fri) else prayer
                            )
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
                                    timezone=ctx.timezone,
                                    evidence=ctx.evidence(
                                        target_label="timetable",
                                        extractor_key=self.key,
                                        extractor_version=self.version,
                                        raw_text=" | ".join(row[:14]),
                                        selector=f"table row {r_idx}",
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
