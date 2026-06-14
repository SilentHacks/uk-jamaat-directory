from __future__ import annotations

import json
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
    key = "ilford_central_mosque_606bf5aa"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("ilfordmosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/ilfordmosque",
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

        m = re.search(r"window\.REDUX_STATE\s*=\s*'([^']*)'", html, re.S)
        if not m:
            m = re.search(r"REDUX_STATE[^']*'([^']+)'", html, re.S)
        if not m:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no REDUX_STATE found in widget",
            )

        try:
            raw = m.group(1)

            def _pct_decode(val: str) -> str:
                def _rep(mm):
                    return chr(int(mm.group(1), 16))

                val = re.sub(r"%([0-9a-fA-F]{2})", _rep, val)
                return val.replace("+", " ")

            decoded = _pct_decode(raw)
            state = json.loads(decoded)
            ath = state.get("masjidbox", {}).get("masjidboxAthany", {})
            timetable = ath.get("timetable") or ath.get("days") or []
        except Exception as exc:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason=f"failed to parse state: {exc}",
            )

        prayer_map = {
            "fajr": Prayer.FAJR,
            "dhuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        for day in timetable:
            if not isinstance(day, dict):
                continue
            dstr = day.get("date") or ""
            try:
                if isinstance(dstr, str) and "T" in dstr:
                    d = datetime.fromisoformat(dstr.replace("Z", "+00:00").split()[0]).date()
                else:
                    d = date.fromisoformat(str(dstr)[:10])
            except Exception:
                continue
            iq = day.get("iqamah") or {}

            for key, prayer in prayer_map.items():
                rawt = iq.get(key)
                if not rawt:
                    continue
                tpart = str(rawt).split("T")[-1].split("+")[0].split("-")[0][:5]
                jt = coerce_time(tpart, prayer=prayer.value)
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{d} {prayer.value}: {rawt!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                win = PLAUSIBLE_WINDOWS.get(prayer.value)
                if win and not (win[0] <= jt <= win[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{d} {prayer.value}: {rawt!r} outside plausible window",
                            target_label="timetable",
                        )
                    )
                    continue
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
                            raw_text=str(rawt),
                            selector=f"iqamah.{key}",
                        ),
                    )
                )

            jumuahs = iq.get("jumuah") or day.get("jumuah") or []
            for idx, rawj in enumerate(jumuahs, start=1):
                if not rawj:
                    continue
                tpart = str(rawj).split("T")[-1].split("+")[0].split("-")[0][:5]
                jt = coerce_time(tpart, prayer="jumuah")
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{d} jumuah: {rawj!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                win = PLAUSIBLE_WINDOWS.get("jumuah")
                if win and not (win[0] <= jt <= win[1]):
                    continue
                rows.append(
                    ExtractorRow(
                        date=d,
                        prayer=Prayer.JUMUAH,
                        jamaat_time=jt,
                        session_number=idx,
                        session_label=f"session {idx}",
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=str(rawj),
                            selector=f"iqamah.jumuah[{idx}]",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
