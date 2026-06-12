from __future__ import annotations

import json
import re
from datetime import date, datetime, time

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS
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
    key = "muhaddith_al_a_zam_mission_d4117750"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("mamissionuk.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/ma-mission-learning-centre",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def _decode_payload(self, s: str) -> str:
        repls = [
            ("%3A", ":"),
            ("%2B", "+"),
            ("%2C", ","),
            ("%22", '"'),
            ("%7B", "{"),
            ("%7D", "}"),
            ("%5B", "["),
            ("%5D", "]"),
            ("%3D", "="),
            ("%2F", "/"),
            ("%20", " "),
            ("%3F", "?"),
            ("%26", "&"),
        ]
        for enc, dec in repls:
            s = s.replace(enc, dec)

        def hexrepl(mo: re.Match[str]) -> str:
            try:
                return bytes.fromhex(mo.group(1)).decode("utf-8", "replace")
            except Exception:
                return mo.group(0)

        s = re.sub(r"%([0-9A-Fa-f]{2})", hexrepl, s)
        return s

    def _parse_time_from_iso(self, s: str | None) -> time | None:
        if not isinstance(s, str) or not s:
            return None
        m = re.search(r"T(\d{2}):(\d{2})", s)
        if m:
            hh, mm = int(m.group(1)), int(m.group(2))
        else:
            m2 = re.search(r"(\d{1,2}):(\d{2})", s)
            if not m2:
                return None
            hh, mm = int(m2.group(1)), int(m2.group(2))
        if not (0 <= hh < 24 and 0 <= mm < 60):
            return None
        return time(hh, mm)

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        m = re.search(r"REDUX_STATE\s*=\s*'([^']+)'", html)
        if not m:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_redux",
                        message="REDUX_STATE not found in page",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no timetable data embedded",
            )
        payload = m.group(1)
        decoded = self._decode_payload(payload)
        try:
            data = json.loads(decoded)
        except Exception as exc:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="bad_json",
                        message=f"failed to parse embedded state: {exc}",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="embedded timetable data malformed",
            )
        ath = data.get("masjidbox", {}).get("masjidboxAthany", {}) if isinstance(data, dict) else {}
        tt = ath.get("timetable", []) or []
        if not tt:
            return ExtractorResult(
                rows=[], no_schedule_reason="no schedule entries in embedded data"
            )
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        target_label = "timetable"
        for entry in tt:
            ds = entry.get("date") or ""
            try:
                if isinstance(ds, str) and "T" in ds:
                    d = datetime.fromisoformat(ds.replace("Z", "+00:00")).date()
                else:
                    d = date.fromisoformat(str(ds)[:10])
            except Exception:
                warnings.append(
                    ExtractorWarning(code="bad_date", message=str(ds), target_label=target_label)
                )
                continue
            iq = entry.get("iqamah") if isinstance(entry.get("iqamah"), dict) else {}
            start_map = {
                "fajr": entry.get("fajr"),
                "dhuhr": entry.get("dhuhr"),
                "asr": entry.get("asr"),
                "maghrib": entry.get("maghrib"),
                "isha": entry.get("isha"),
            }
            jumuah_starts = entry.get("jumuah") or []
            for pkey, prayer in [
                ("fajr", Prayer.FAJR),
                ("dhuhr", Prayer.DHUHR),
                ("asr", Prayer.ASR),
                ("maghrib", Prayer.MAGHRIB),
                ("isha", Prayer.ISHA),
            ]:
                jraw = iq.get(pkey) if isinstance(iq, dict) else None
                if not jraw:
                    continue
                jamaat = self._parse_time_from_iso(jraw)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{d} {pkey}: {jraw!r}",
                            target_label=target_label,
                        )
                    )
                    continue
                window = PLAUSIBLE_WINDOWS.get(prayer.value)
                if window and not (window[0] <= jamaat <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{d} {prayer.value}: {jraw!r} outside plausible window",
                            target_label=target_label,
                        )
                    )
                    continue
                sraw = start_map.get(pkey)
                start = self._parse_time_from_iso(sraw) if sraw else None
                rows.append(
                    ExtractorRow(
                        date=d,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        start_time=start,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label=target_label,
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"date={ds} {pkey}_iq={jraw}",
                            selector="redux iqamah",
                        ),
                    )
                )
            jiq_list = iq.get("jumuah") if isinstance(iq, dict) else None
            jiq_list = jiq_list or []
            for i, jraw in enumerate(jiq_list):
                if not jraw:
                    continue
                jamaat = self._parse_time_from_iso(jraw)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{d} jumuah: {jraw!r}",
                            target_label=target_label,
                        )
                    )
                    continue
                window = PLAUSIBLE_WINDOWS.get(Prayer.JUMUAH.value)
                if window and not (window[0] <= jamaat <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{d} jumuah: {jraw!r} outside plausible window",
                            target_label=target_label,
                        )
                    )
                    continue
                sraw = jumuah_starts[i] if i < len(jumuah_starts) else None
                start = self._parse_time_from_iso(sraw) if sraw else None
                rows.append(
                    ExtractorRow(
                        date=d,
                        prayer=Prayer.JUMUAH,
                        jamaat_time=jamaat,
                        start_time=start,
                        session_number=i + 1,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label=target_label,
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"date={ds} jumuah_iq={jraw}",
                            selector="redux jumuah",
                        ),
                    )
                )
        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
