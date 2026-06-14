import re
from datetime import date

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
    key = "masjid_umar_94d8b3a6"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("masjidumarcardiff.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/masjid-umar-1652978671870",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    _PRAYER_KEYS = [
        (Prayer.FAJR, "fajr"),
        (Prayer.DHUHR, "dhuhr"),
        (Prayer.ASR, "asr"),
        (Prayer.MAGHRIB, "maghrib"),
        (Prayer.ISHA, "isha"),
    ]

    def _clock(self, iso: str) -> str:
        try:
            if isinstance(iso, str):
                m = re.search(r"T(\d{2}:\d{2})", iso)
                if m:
                    return m.group(1)
                return iso.split("T")[-1][:5]
        except Exception:
            pass
        return str(iso)[:5]

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()

        match = re.search(r"window\.REDUX_STATE\s*=\s*'([^']+)'", html)
        if not match:
            match = re.search(r'window\.REDUX_STATE\s*=\s*"([^"]+)"', html)
        if not match:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="REDUX_STATE not found",
                warnings=[
                    ExtractorWarning(
                        code="no_redux_state",
                        message="window.REDUX_STATE JSON not present in page",
                        target_label="timetable",
                    )
                ],
            )

        try:
            raw = match.group(1)

            def _pct_decode(val: str) -> str:
                def _rep(m):
                    return chr(int(m.group(1), 16))

                val = re.sub(r"%([0-9a-fA-F]{2})", _rep, val)
                return val.replace("+", " ")

            decoded = _pct_decode(raw)
        except Exception:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="REDUX_STATE decode error",
                warnings=[
                    ExtractorWarning(
                        code="redux_decode_error",
                        message="failed to percent-decode REDUX_STATE",
                        target_label="timetable",
                    )
                ],
            )

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        tpos = decoded.find('"timetable"')
        if tpos < 0:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable marker not found in REDUX_STATE",
                warnings=[
                    ExtractorWarning(
                        code="no_timetable_marker",
                        message='no "timetable" key in decoded REDUX_STATE',
                        target_label="timetable",
                    )
                ],
            )

        def _extract_object(text: str, start: int) -> str | None:
            j = text.find("{", start)
            if j < 0:
                return None
            depth = 0
            for idx in range(j, min(j + 8000, len(text))):
                ch = text[idx]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[j : idx + 1]
            return None

        def _parse_kv_object(obj: str) -> dict[str, object]:
            res: dict[str, object] = {}
            for m in re.finditer(r'"([^"]+)"\s*:\s*"([^"]*)"', obj):
                res[m.group(1)] = m.group(2)
            for m in re.finditer(r'"([^"]+)"\s*:\s*\[([^\]]*)\]', obj):
                k = m.group(1)
                vals = re.findall(r'"([^"]*)"', m.group(2))
                res[k] = vals
            return res

        def _find_iqamah(text: str) -> dict[str, object]:
            pos = text.find('"iqamah"')
            if pos < 0:
                return {}
            sub = _extract_object(text, pos)
            if sub:
                return _parse_kv_object(sub)
            return {}

        date_re = re.compile(r'"date":"(\d{4}-\d{2}-\d{2}[^"]*)"')
        for dm in date_re.finditer(decoded, tpos):
            dpart = dm.group(1).split("T")[0]
            try:
                row_date = date.fromisoformat(dpart)
            except Exception:
                warnings.append(
                    ExtractorWarning(
                        code="bad_date",
                        message=f"could not parse date {dm.group(1)!r}",
                        target_label="timetable",
                    )
                )
                continue

            next_dm = date_re.search(decoded, dm.end())
            end = next_dm.start() if next_dm else dm.start() + 6000
            window = decoded[dm.start() : end]

            starts: dict[str, str] = {}
            for prayer, key in self._PRAYER_KEYS:
                mst = re.search(rf'"{key}"\s*:\s*"([^"]*)"', window)
                if mst:
                    starts[key] = mst.group(1)

            iqamah: dict[str, object] = _find_iqamah(window)

            for prayer, key in self._PRAYER_KEYS:
                raw_j = iqamah.get(key)
                if not raw_j or not isinstance(raw_j, str):
                    continue
                j = coerce_time(self._clock(raw_j), prayer=prayer.value)
                if j is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {raw_j!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                wp = PLAUSIBLE_WINDOWS.get(prayer.value)
                if wp and not (wp[0] <= j <= wp[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{row_date} {prayer.value}: {raw_j!r} outside plausible window",
                            target_label="timetable",
                        )
                    )
                    continue
                start = None
                rs = starts.get(key)
                if rs:
                    start = coerce_time(self._clock(rs), prayer=prayer.value)

                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=j,
                        start_time=start,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{row_date} {key} iqamah={raw_j}",
                            selector="REDUX_STATE.timetable[].iqamah",
                        ),
                    )
                )

            jumuah_j = iqamah.get("jumuah")
            if isinstance(jumuah_j, list):
                for idx, raw_ju in enumerate(jumuah_j, start=1):
                    if not isinstance(raw_ju, str) or not raw_ju:
                        continue
                    ju = coerce_time(self._clock(raw_ju), prayer="jumuah")
                    if ju is None:
                        warnings.append(
                            ExtractorWarning(
                                code="unparseable_time",
                                message=f"{row_date} jumuah[{idx}]: {raw_ju!r}",
                                target_label="timetable",
                            )
                        )
                        continue
                    wj = PLAUSIBLE_WINDOWS.get("jumuah") or PLAUSIBLE_WINDOWS.get("dhuhr")
                    if wj and not (wj[0] <= ju <= wj[1]):
                        continue
                    rows.append(
                        ExtractorRow(
                            date=row_date,
                            prayer=Prayer.JUMUAH,
                            jamaat_time=ju,
                            session_number=idx,
                            session_label=f"session {idx}",
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"{row_date} jumuah iqamah={raw_ju}",
                                selector=f"REDUX_STATE.timetable[].iqamah.jumuah[{idx}]",
                            ),
                        )
                    )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
