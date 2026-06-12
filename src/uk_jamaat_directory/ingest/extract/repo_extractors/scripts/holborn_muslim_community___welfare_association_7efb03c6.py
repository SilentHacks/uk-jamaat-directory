from __future__ import annotations

import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
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
    key = "holborn_muslim_community___welfare_association_7efb03c6"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("holbornmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/holborn-mosque",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        text = artifact.text()
        timetable = self._parse_timetable(text)
        if not timetable:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no timetable data in artifact",
                warnings=[
                    ExtractorWarning(
                        code="no_timetable_blob",
                        message="could not locate masjidbox timetable array",
                        target_label="timetable",
                    )
                ],
            )
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        for day in timetable:
            if not isinstance(day, dict):
                continue
            d = self._parse_day(day.get("date"))
            if d is None:
                continue
            iq = day.get("iqamah") or {}
            if isinstance(iq, dict):
                for k, pr in (
                    ("fajr", Prayer.FAJR),
                    ("dhuhr", Prayer.DHUHR),
                    ("asr", Prayer.ASR),
                    ("maghrib", Prayer.MAGHRIB),
                    ("isha", Prayer.ISHA),
                ):
                    val = iq.get(k)
                    if isinstance(val, str):
                        hm = self._iso_hm(val)
                        if hm:
                            jt = coerce_time(hm, prayer=pr.value)
                            if jt:
                                rows.append(
                                    ExtractorRow(
                                        date=d,
                                        prayer=pr,
                                        jamaat_time=jt,
                                        timezone=ctx.timezone,
                                        evidence=ctx.evidence(
                                            target_label="timetable",
                                            extractor_key=self.key,
                                            extractor_version=self.version,
                                            raw_text=val,
                                            selector="iqamah." + k,
                                        ),
                                    )
                                )
                            else:
                                warnings.append(
                                    ExtractorWarning(
                                        code="unparseable",
                                        message=f"{d} {k} {val}",
                                        target_label="timetable",
                                    )
                                )
            jlist = day.get("jumuah") or []
            if not jlist and isinstance(iq, dict):
                jv = iq.get("jumuah")
                if isinstance(jv, list):
                    jlist = jv
            if isinstance(jlist, list):
                for idx, jv in enumerate(jlist, 1):
                    if isinstance(jv, str):
                        hm = self._iso_hm(jv)
                        if hm:
                            jt = coerce_time(hm, prayer="jumuah")
                            if jt:
                                rows.append(
                                    ExtractorRow(
                                        date=d,
                                        prayer=Prayer.JUMUAH,
                                        jamaat_time=jt,
                                        session_number=idx,
                                        session_label=(f"session {idx}" if idx > 1 else None),
                                        timezone=ctx.timezone,
                                        evidence=ctx.evidence(
                                            target_label="timetable",
                                            extractor_key=self.key,
                                            extractor_version=self.version,
                                            raw_text=jv,
                                            selector="jumuah",
                                        ),
                                    )
                                )
        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable jamaat rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)

    def _unpct(self, s: str) -> str:
        def rep(m: re.Match[str]) -> str:
            return chr(int(m.group(1), 16))

        return re.sub(r"%([0-9A-Fa-f]{2})", rep, s)

    def _parse_timetable(self, text: str) -> list[dict]:
        # Masjidbox pages embed the full timetable as a percent-encoded JSON array
        # inside a JS string in the initial HTML (e.g. %22timetable%22%3A%5B...%5D).
        # We must decode that to see real "date", "iqamah" keys.
        m = re.search(r"%22timetable%22%3A(%5B.+?)%2C%22isStale%22", text, re.DOTALL)
        if not m:
            m = re.search(r"%22timetable%22%3A(%5B[\s\S]{2000,}?%5D)", text)
        if m:
            arrenc = m.group(1)
            # ensure it ends with array close if the pattern cut early
            if not arrenc.rstrip().endswith("%5D"):
                arrenc = arrenc + "%5D"
            clean = self._unpct(arrenc)
            days: list[dict] = []
            for dm in re.finditer(r'"date"\s*:\s*"([^"]+)"', clean):
                dstr = dm.group(1)
                st = dm.end()
                win = clean[st : st + 4000]
                iq: dict[str, object] = {}
                mi = re.search(r'"iqamah"\s*:\s*\{(.*?)\}', win, re.DOTALL)
                if mi:
                    inner = mi.group(1)
                    for pk in ("fajr", "dhuhr", "asr", "maghrib", "isha"):
                        mm = re.search(rf'"{pk}"\s*:\s*"([^"]*)"', inner)
                        if mm:
                            iq[pk] = mm.group(1)
                    mj = re.search(r'"jumuah"\s*:\s*\[(.*?)\]', inner, re.DOTALL)
                    if mj:
                        jvals = re.findall(r'"([^"]+)"', mj.group(1))
                        if jvals:
                            iq["jumuah"] = jvals
                jlist: list[str] = []
                mj2 = re.search(r'"jumuah"\s*:\s*\[(.*?)\]', win, re.DOTALL)
                if mj2:
                    jlist = re.findall(r'"([^"]+)"', mj2.group(1))
                rec: dict[str, object] = {"date": dstr, "iqamah": iq}
                if jlist:
                    rec["jumuah"] = jlist
                days.append(rec)
            if days:
                return days
        # Fallbacks for other possible embeddings (rare)
        for src in (text, text.replace('\\"', '"').replace("\\\\", "\\")):
            days = []
            for m in re.finditer(r'"date"\s*:\s*"([^"]+)"', src):
                dstr = m.group(1)
                start = m.end()
                window = src[start : start + 2000]
                iq = {}
                mi = re.search(r'"iqamah"\s*:\s*\{([^}]*)\}', window)
                if mi:
                    inner = mi.group(1)
                    for pk in ("fajr", "dhuhr", "asr", "maghrib", "isha"):
                        mm = re.search(rf'"{pk}"\s*:\s*"([^"]*)"', inner)
                        if mm:
                            iq[pk] = mm.group(1)
                    ma = re.search(r'"jumuah"\s*:\s*\[([^\]]*)\]', inner)
                    if ma:
                        arrs = re.findall(r'"([^"]+)"', ma.group(1))
                        if arrs:
                            iq["jumuah"] = arrs
                jlist = []
                mj = re.search(r'"jumuah"\s*:\s*\[([^\]]*)\]', window)
                if mj:
                    jlist = re.findall(r'"([^"]+)"', mj.group(1))
                rec = {"date": dstr, "iqamah": iq}
                if jlist:
                    rec["jumuah"] = jlist
                days.append(rec)
            if days:
                return days
        return []

    def _parse_day(self, val: str | None) -> date | None:
        if not val:
            return None
        try:
            return datetime.fromisoformat(val.replace(" ", "")).date()
        except Exception:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", val)
            if m:
                try:
                    return datetime.strptime(m.group(1), "%Y-%m-%d").date()
                except Exception:
                    return None
        return None

    def _iso_hm(self, val: str | None) -> str | None:
        if not val or not isinstance(val, str):
            return None
        m = re.search(r"T(\d{2}:\d{2})", val)
        return m.group(1) if m else None
