from __future__ import annotations

import re
from datetime import datetime

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


def _url_decode(encoded: str) -> str:
    """Decode URL-encoded string (%XX format)."""

    def replace_hex(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    return re.sub(r"%([0-9A-Fa-f]{2})", replace_hex, encoded)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "masjid_ibrahim_36a88b39"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("masjidibrahim.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/ukim-masjid-ibrahim",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = (
            artifact.body.decode("utf-8", errors="ignore")
            if isinstance(artifact.body, bytes)
            else artifact.body
        )

        redux_match = re.search(r'REDUX_STATE\s*=\s*["\']([^"\']*)["\']', html)
        if not redux_match:
            return ExtractorResult(rows=[], no_schedule_reason="could not find REDUX_STATE")

        state_encoded = redux_match.group(1)
        state_json = _url_decode(state_encoded)

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        target_label = "timetable"

        timetable_start = state_json.find('"timetable":[')
        if timetable_start < 0:
            return ExtractorResult(rows=[], no_schedule_reason="could not find timetable")

        bracket_start = state_json.find("[", timetable_start)
        if bracket_start < 0:
            return ExtractorResult(rows=[], no_schedule_reason="could not find timetable bracket")

        date_pattern = r'"date":"(\d{4}-\d{2}-\d{2})T[^"]+"'
        prayer_map = {
            "fajr": Prayer.FAJR,
            "dhuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        for date_match in re.finditer(date_pattern, state_json[bracket_start:]):
            try:
                date_str = date_match.group(1)
                date_obj = datetime.fromisoformat(date_str).date()
            except Exception:
                continue

            date_start = bracket_start + date_match.start()
            date_end = state_json.find('},{"date', date_start + 1)
            if date_end < 0:
                date_end = len(state_json)
            day_obj = state_json[date_start:date_end]

            is_friday = date_obj.weekday() == 4

            iqamah_match = re.search(r'"iqamah":\{([^}]*)\}', day_obj)
            if not iqamah_match:
                continue
            iqamah_str = iqamah_match.group(1)

            has_jumuah_list = bool(re.search(r'"jumuah":\[', iqamah_str))

            for prayer_key, prayer_enum in prayer_map.items():
                if prayer_key == "dhuhr" and has_jumuah_list:
                    # explicit jumuah list will cover the Friday congregation(s)
                    continue
                iqamah_pattern = f'"{prayer_key}":"([^"]+)"'
                iq_pr = re.search(iqamah_pattern, iqamah_str)
                if not iq_pr:
                    continue
                try:
                    time_str = iq_pr.group(1)
                    tm = re.search(r"T(\d{2}):(\d{2})", time_str)
                    if not tm:
                        continue
                    h, mi = int(tm.group(1)), int(tm.group(2))
                    tstr = f"{h}:{mi:02d}"
                    pt = coerce_time(tstr, prayer=prayer_key)
                    if pt is None:
                        continue
                    window = PLAUSIBLE_WINDOWS.get(prayer_key)
                    if window and not (window[0] <= pt <= window[1]):
                        warnings.append(
                            ExtractorWarning(
                                code="implausible_time",
                                message=(
                                    f"{date_obj} {prayer_key}: {tstr!r} outside plausible window"
                                ),
                                target_label=target_label,
                            )
                        )
                        continue
                    if is_friday and prayer_enum == Prayer.DHUHR:
                        emitted = Prayer.JUMUAH
                    else:
                        emitted = prayer_enum
                    sess = 1 if emitted == Prayer.JUMUAH else None
                    rows.append(
                        ExtractorRow(
                            date=date_obj,
                            prayer=emitted,
                            jamaat_time=pt,
                            session_number=sess,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label=target_label,
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"{prayer_key}: {tstr}",
                                selector="masjidbox iqamah",
                            ),
                        )
                    )
                except Exception:
                    continue

            # explicit jumuah sessions (multiple on Friday)
            jiq_match = re.search(r'"jumuah":\[([^\]]*)\]', iqamah_str)
            if jiq_match:
                jlist_str = jiq_match.group(1)
                jtimes = re.findall(r'"([^"]+)"', jlist_str)
                jstart_match = re.search(r'"jumuah":\[([^\]]*)\]', day_obj)
                jstarts: list[str] = []
                if jstart_match:
                    jstarts = re.findall(r'"([^"]+)"', jstart_match.group(1))
                for idx, jraw in enumerate(jtimes):
                    try:
                        tm = re.search(r"T(\d{2}):(\d{2})", jraw)
                        if not tm:
                            continue
                        h, mi = int(tm.group(1)), int(tm.group(2))
                        tstr = f"{h}:{mi:02d}"
                        pt = coerce_time(tstr, prayer="jumuah")
                        if pt is None:
                            continue
                        win = PLAUSIBLE_WINDOWS.get("jumuah")
                        if win and not (win[0] <= pt <= win[1]):
                            warnings.append(
                                ExtractorWarning(
                                    code="implausible_time",
                                    message=f"{date_obj} jumuah: {tstr!r} outside plausible window",
                                    target_label=target_label,
                                )
                            )
                            continue
                        start = None
                        if idx < len(jstarts):
                            sraw = jstarts[idx]
                            stm = re.search(r"T(\d{2}):(\d{2})", sraw)
                            if stm:
                                sh, sm = int(stm.group(1)), int(stm.group(2))
                                start = coerce_time(f"{sh}:{sm:02d}", prayer="jumuah")
                        rows.append(
                            ExtractorRow(
                                date=date_obj,
                                prayer=Prayer.JUMUAH,
                                jamaat_time=pt,
                                start_time=start,
                                session_number=idx + 1,
                                timezone=ctx.timezone,
                                evidence=ctx.evidence(
                                    target_label=target_label,
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    raw_text=f"jumuah_iq={jraw}",
                                    selector="masjidbox jumuah",
                                ),
                            )
                        )
                    except Exception:
                        continue

        # deduplicate by (date, prayer, session)
        seen: set[tuple] = set()
        deduped: list[ExtractorRow] = []
        for r in rows:
            key = (r.date, r.prayer, r.session_number or 1)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)

        if not deduped:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=deduped, warnings=warnings)
