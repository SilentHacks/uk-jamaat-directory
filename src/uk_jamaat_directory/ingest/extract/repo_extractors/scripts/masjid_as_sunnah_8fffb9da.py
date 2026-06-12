from __future__ import annotations

import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
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
    key = "masjid_as_sunnah_8fffb9da"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("albaseerah.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://albaseerah.com/monthly-prayer-timetable",
                kind=TargetKind.RENDERED_HTML,
                requires_javascript=True,
            ),
        )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []
        seen: set[tuple[date, str]] = set()

        # 1) Try to parse a populated monthly grid if the plugin pre-filled values (rare on cold load).
        m = re.search(
            r'<div[^>]*class=["\'][^"\']*time-grid[^"\']*["\'][^>]*>(.*?)</div>\s*</div>',
            html,
            re.I | re.S,
        )
        grid_html = m.group(1) if m else ""
        input_vals: list[str] = (
            re.findall(r'<input[^>]*value=["\']([^"\']*)["\']', grid_html, re.I)
            if grid_html
            else []
        )
        if len(input_vals) < 13:
            input_vals = re.findall(r'<input[^>]*value=["\']([^"\']*)["\']', html, re.I)

        COLS = 13
        today = datetime.now().date()
        year = today.year
        month = today.month
        for i in range(0, max(0, len(input_vals) - (COLS - 1)), COLS):
            chunk = input_vals[i : i + COLS]
            day_str = (chunk[0] or "").strip() if chunk else ""
            day = None
            mday = re.search(r"(\d{1,2})", day_str)
            if mday:
                try:
                    day = int(mday.group(1))
                except Exception:
                    day = None
            if day is None or not (1 <= day <= 31):
                continue
            try:
                d = date(year, month, day)
            except ValueError:
                continue

            def add(prayer: Prayer, raw: str, selector: str) -> None:
                if not raw:
                    return
                jt = coerce_time(raw.replace(".", ":"), prayer=prayer.value)
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{d} {prayer.value}: {raw!r}",
                            target_label="timetable",
                        )
                    )
                    return
                win = PLAUSIBLE_WINDOWS.get(prayer.value)
                if win and not (win[0] <= jt <= win[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{d} {prayer.value}: {raw!r} outside plausible window",
                            target_label="timetable",
                        )
                    )
                    return
                k = (d, prayer.value)
                if k in seen:
                    return
                seen.add(k)
                rows.append(
                    ExtractorRow(
                        date=d,
                        prayer=prayer,
                        jamaat_time=jt,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=raw,
                            selector=selector,
                        ),
                    )
                )

            if 4 < len(chunk):
                add(Prayer.FAJR, (chunk[4] or "").strip(), "grid-col-4-fajr-jamaah")
            if 9 < len(chunk):
                add(Prayer.ASR, (chunk[9] or "").strip(), "grid-col-9-asr-jamaah")
            if 12 < len(chunk):
                add(Prayer.ISHA, (chunk[12] or "").strip(), "grid-col-12-ishaa-jamaah")
            if 10 < len(chunk):
                add(Prayer.MAGHRIB, (chunk[10] or "").strip(), "grid-col-10-maghrib")
            slot7 = (chunk[7] or "").strip() if 7 < len(chunk) else ""
            if slot7:
                if d.weekday() == 4:
                    add(Prayer.JUMUAH, slot7, "grid-col-7-jumuah")
                else:
                    add(Prayer.DHUHR, slot7, "grid-col-7-duhr-jamaat")
            if d.weekday() != 4 and 6 < len(chunk):
                slot6 = (chunk[6] or "").strip()
                if slot6:
                    add(Prayer.DHUHR, slot6, "grid-col-6-duhr")

        # 2) Fallback: parse the visible "today" congregational bar (pt_header_bar / dpt_jamah).
        #    The monthly grid is JS-populated on month select; the bar always shows today's jamaat times.
        if not rows:
            prayer_map = {
                "pt_fajr": Prayer.FAJR,
                "pt_dhuhr": Prayer.DHUHR,
                "pt_duhr": Prayer.DHUHR,
                "pt_asr": Prayer.ASR,
                "pt_maghrib": Prayer.MAGHRIB,
                "pt_isha": Prayer.ISHA,
                "pt_ishaa": Prayer.ISHA,
                "pt_jumuah": Prayer.JUMUAH,
                "pt_jummah": Prayer.JUMUAH,
            }
            # The pt_prayer containers are nested; search by class marker then look ahead
            # a short window for the associated dpt_jamah span (avoids fragile nested div matching).
            for m in re.finditer(
                r'class=["\'][^"\']*(pt_fajr|pt_dhuhr|pt_duhr|pt_asr|pt_maghrib|pt_isha|pt_ishaa|pt_jumuah|pt_jummah)[^"\']*["\']',
                html,
                re.I,
            ):
                cls = m.group(1).lower()
                prayer = prayer_map.get(cls)
                if not prayer:
                    continue
                start = m.end()
                win = html[start : start + 800]
                jam = re.search(r"<span[^>]*dpt_jamah[^>]*>([^<]*)</span>", win, re.I)
                if not jam:
                    continue
                raw = (jam.group(1) or "").strip()
                if not raw:
                    continue
                d = today
                jt = coerce_time(raw.replace(".", ":"), prayer=prayer.value)
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{d} {prayer.value}: {raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                winw = PLAUSIBLE_WINDOWS.get(prayer.value)
                if winw and not (winw[0] <= jt <= winw[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{d} {prayer.value}: {raw!r} outside plausible window",
                            target_label="timetable",
                        )
                    )
                    continue
                k = (d, prayer.value)
                if k in seen:
                    continue
                seen.add(k)
                rows.append(
                    ExtractorRow(
                        date=d,
                        prayer=prayer,
                        jamaat_time=jt,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=raw,
                            selector=f"today-bar-{cls}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable jamaat rows",
            )
        return ExtractorResult(rows=rows, warnings=warnings)
