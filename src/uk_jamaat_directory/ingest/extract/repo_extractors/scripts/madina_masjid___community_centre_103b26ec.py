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


def _find_balanced(text: str, start_char: str, end_char: str, pos: int) -> str | None:
    """Return the balanced substring starting at the first start_char at/after pos."""
    i = text.find(start_char, pos)
    if i == -1:
        return None
    depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c == start_char:
            depth += 1
        elif c == end_char:
            depth -= 1
            if depth == 0:
                return text[i : j + 1]
    return None


def _extract_iqama_calendar(text: str) -> list[dict] | None:
    """Locate iqamaCalendar:[ {..}, ... ] and return list of month dicts (day->list[str])."""
    m = re.search(r'"iqamaCalendar"\s*:\s*\[', text)
    if not m:
        return None
    arr_text = _find_balanced(text, "[", "]", m.end() - 1)
    if not arr_text:
        return None
    months: list[dict] = []
    # Each month is an object { "1":[..], "2":[..], ... }
    # Find successive { ... } inside the array
    pos = 0
    while True:
        obj = _find_balanced(arr_text, "{", "}", pos)
        if obj is None:
            break
        pos = arr_text.find(obj, pos) + len(obj)
        month_dict: dict[str, list[str]] = {}
        # Extract "D":[ "HH:MM", ... ] entries
        for dm in re.finditer(r'"(\d{1,2})"\s*:\s*\[([^\]]*)\]', obj):
            day = dm.group(1)
            vals_raw = dm.group(2)
            vals = [v.strip().strip('"').strip("'") for v in re.findall(r'"([^"]*)"', vals_raw)]
            if vals:
                month_dict[day] = vals
        if month_dict:
            months.append(month_dict)
    return months or None


def _extract_jumua(text: str) -> tuple[str | None, str | None]:
    j1 = None
    j2 = None
    m1 = re.search(r'"jumua"\s*:\s*"([^"]*)"', text)
    if m1:
        j1 = m1.group(1).strip()
    m2 = re.search(r'"jumua2"\s*:\s*"([^"]*)"', text)
    if m2:
        j2 = m2.group(1).strip()
    return j1 or None, j2 or None


def _extract_adhan_calendar(text: str) -> list[dict] | None:
    m = re.search(r'"calendar"\s*:\s*\[', text)
    if not m:
        return None
    arr_text = _find_balanced(text, "[", "]", m.end() - 1)
    if not arr_text:
        return None
    months: list[dict] = []
    pos = 0
    while True:
        obj = _find_balanced(arr_text, "{", "}", pos)
        if obj is None:
            break
        pos = arr_text.find(obj, pos) + len(obj)
        month_dict: dict[str, list[str]] = {}
        for dm in re.finditer(r'"(\d{1,2})"\s*:\s*\[([^\]]*)\]', obj):
            day = dm.group(1)
            vals_raw = dm.group(2)
            vals = [v.strip().strip('"').strip("'") for v in re.findall(r'"([^"]*)"', vals_raw)]
            if vals:
                month_dict[day] = vals
        if month_dict:
            months.append(month_dict)
    return months or None


class Extractor(BaseMosqueWebsiteExtractor):
    key = "madina_masjid___community_centre_103b26ec"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("madinamasjidukim.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://mawaqit.net/en/w/madina-masjid-levenshulme-manchester-m19-3dj-united-kingdom?showOnly5PrayerTimes=0",
            kind=TargetKind.HTML,
        ),
    )

    target_label: str = "timetable"

    def current_year(self, ctx: ExtractContext) -> int:
        return datetime.now().year

    def current_month(self, ctx: ExtractContext) -> int:
        return datetime.now().month

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        text = artifact.text()
        iqama_calendar = _extract_iqama_calendar(text)
        if not iqama_calendar:
            return ExtractorResult(rows=[], no_schedule_reason="no iqamaCalendar in widget data")

        adhan_calendar = _extract_adhan_calendar(text) or []
        jumua_raw, jumua2_raw = _extract_jumua(text)

        year = self.current_year(ctx)
        month = self.current_month(ctx)
        month_idx = month - 1
        if month_idx < 0 or month_idx >= len(iqama_calendar) or not iqama_calendar[month_idx]:
            for idx, mdata in enumerate(iqama_calendar):
                if mdata:
                    month_idx = idx
                    break
            else:
                return ExtractorResult(
                    rows=[], no_schedule_reason="no usable month data in iqamaCalendar"
                )

        month_iq: dict = iqama_calendar[month_idx]
        month_ad: dict = (
            adhan_calendar[month_idx]
            if month_idx < len(adhan_calendar) and adhan_calendar[month_idx]
            else {}
        )

        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []
        prayer_map = [Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA]

        cur_month_for_days = (
            month if (month_idx == self.current_month(ctx) - 1) else (month_idx + 1)
        )

        for day_key in sorted(
            month_iq.keys(), key=lambda x: int(x) if str(x).lstrip("-").isdigit() else 999
        ):
            try:
                day = int(day_key)
                row_date = date(year, cur_month_for_days, day)
            except Exception:
                continue

            iq_list = month_iq.get(day_key) or []
            ad_list = month_ad.get(day_key) or []

            for pidx, prayer in enumerate(prayer_map):
                raw = str(iq_list[pidx]).strip() if pidx < len(iq_list) else ""
                if not raw or raw.lower() in ("", "null", "none"):
                    continue
                if raw in ("+0", "+ 0", "+0 "):
                    raw = str(ad_list[pidx]).strip() if pidx < len(ad_list) else ""
                    if not raw:
                        continue
                jt = coerce_time(raw, prayer=prayer.value)
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {raw!r}",
                            target_label=self.target_label,
                        )
                    )
                    continue
                window = PLAUSIBLE_WINDOWS.get(prayer.value)
                if window and not (window[0] <= jt <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{row_date} {prayer.value}: {raw!r} outside plausible window",
                            target_label=self.target_label,
                        )
                    )
                    continue
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jt,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label=self.target_label,
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{day_key} | {prayer.value} | {raw}",
                            selector=f"iqamaCalendar[{month_idx}][{day_key}]",
                        ),
                    )
                )

        # Jumuah sessions (often 1 or 2) on Fridays
        for d in range(1, 32):
            try:
                fd = date(year, cur_month_for_days, d)
            except ValueError:
                continue
            if fd.weekday() != 4:  # Friday
                continue
            for sess, jraw in enumerate([jumua_raw or "", jumua2_raw or ""], start=1):
                if not jraw:
                    continue
                jt = coerce_time(jraw, prayer="jumuah")
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{fd} jumuah: {jraw!r}",
                            target_label=self.target_label,
                        )
                    )
                    continue
                rows.append(
                    ExtractorRow(
                        date=fd,
                        prayer=Prayer.JUMUAH,
                        jamaat_time=jt,
                        session_number=sess,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label=self.target_label,
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"jumua{sess} | {jraw}",
                            selector=f"jumua{sess}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable jamaat rows"
            )

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
