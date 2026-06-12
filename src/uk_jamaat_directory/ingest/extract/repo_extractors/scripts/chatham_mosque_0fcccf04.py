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
    key = "chatham_mosque_0fcccf04"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("chathamhillmosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.chathamhillmosque.co.uk/prayer-times",
            kind=TargetKind.HTML,
        ),
    )

    _PRAYER_KEYS = [
        (Prayer.FAJR, "fajr"),
        (Prayer.DHUHR, "dhuhr"),
        (Prayer.ASR, "asr"),
        (Prayer.MAGHRIB, "maghrib"),
        (Prayer.ISHA, "isha"),
    ]

    @staticmethod
    def _clock(raw: str | None) -> str | None:
        """Normalize an ISO datetime or clock string to a plain HH:MM clock for coerce_time."""
        if not raw:
            return None
        s = str(raw).strip()
        if not s:
            return None
        # If ISO-like (contains T or a date prefix), extract the time portion after T or last space
        if "T" in s or re.match(r"^\d{4}-\d{2}-\d{2}", s):
            # after T or after space
            if "T" in s:
                s = s.split("T", 1)[1]
            else:
                # e.g. "2026-06-12 04:00:00+01:00"
                parts = s.split(None, 1)
                if len(parts) > 1:
                    s = parts[1]
            # strip TZ suffix +00:00 / +01:00 / Z etc.
            for sep in ("+", "-", "Z", "z"):
                if sep in s:
                    # keep only before the first +/-/Z that starts a tz
                    # but '-' can be in date too; since we already split T, the first - after HH is tz
                    idx = s.find(sep)
                    if idx > 0:
                        # if sep is after at least HH:MM, treat as tz start
                        cand = s[:idx]
                        if re.match(r"^\d{1,2}(:\d{2})?(:\d{2})?$", cand):
                            s = cand
                            break
            # drop seconds if present
            if s.count(":") == 2:
                s = s.rsplit(":", 1)[0]
        # final cleanup: keep only leading HH:MM or H:MM
        m = re.match(r"^\s*(\d{1,2}(:\d{2})?)", s)
        if m:
            return m.group(1)
        return s.strip()

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()

        # The page embeds the full schedule (including explicit iqamah/jamaat times)
        # as a URL-encoded JSON blob in window.REDUX_STATE.
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
            # REDUX_STATE is a percent-encoded JSON string in the served HTML/JS.
            # Decode with pure re (no urllib, no json module per import rules).
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

        # Bound search to the timetable region.
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
            """Return the {...} object starting at or after 'start' by brace matching."""
            j = text.find("{", start)
            if j < 0:
                return None
            depth = 0
            for idx in range(j, min(j + 4000, len(text))):
                ch = text[idx]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[j : idx + 1]
            return None

        def _parse_kv_object(obj: str) -> dict[str, object]:
            """Parse a small flat object (or with one array) using re only."""
            res: dict[str, object] = {}
            for m in re.finditer(r'"([^"]+)"\s*:\s*"([^"]*)"', obj):
                res[m.group(1)] = m.group(2)
            for m in re.finditer(r'"([^"]+)"\s*:\s*\[([^\]]*)\]', obj):
                k = m.group(1)
                vals = re.findall(r'"([^"]*)"', m.group(2))
                res[k] = vals
            return res

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
            end = next_dm.start() if next_dm else dm.start() + 3000
            window = decoded[dm.start() : end]

            # Top-level adhan starts for standard prayers in this item window.
            starts: dict[str, str] = {}
            for prayer, key in self._PRAYER_KEYS:
                mst = re.search(rf'"{key}"\s*:\s*"([^"]*)"', window)
                if mst:
                    starts[key] = mst.group(1)

            # Top-level jumuah adhan list (for session start times), if present.
            jumuah_starts: list[str] = []
            mju = re.search(r'"jumuah"\s*:\s*\[([^\]]*)\]', window)
            if mju:
                jumuah_starts = re.findall(r'"([^"]*)"', mju.group(1))

            # iqamah sub-object (contains jamaat times).
            iq_obj = _extract_object(window, 0)
            iqamah: dict[str, object] = {}
            if iq_obj and '"iqamah"' in iq_obj:
                iq_sub = _extract_object(iq_obj, iq_obj.find('"iqamah"'))
                if iq_sub:
                    iqamah = _parse_kv_object(iq_sub)

            # Standard prayers: jamaat from iqamah, start from top-level.
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

            # Jumuah sessions from iqamah.jumuah (explicit congregation times).
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
                        warnings.append(
                            ExtractorWarning(
                                code="implausible_time",
                                message=f"{row_date} jumuah[{idx}]: {raw_ju!r} outside plausible window",
                                target_label="timetable",
                            )
                        )
                        continue
                    ju_start = None
                    if idx - 1 < len(jumuah_starts):
                        ju_start = coerce_time(self._clock(jumuah_starts[idx - 1]), prayer="jumuah")

                    rows.append(
                        ExtractorRow(
                            date=row_date,
                            prayer=Prayer.JUMUAH,
                            jamaat_time=ju,
                            start_time=ju_start,
                            session_number=idx,
                            session_label=f"session {idx}",
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"{row_date} jumuah[{idx}]={raw_ju}",
                                selector="REDUX_STATE.timetable[].iqamah.jumuah",
                            ),
                        )
                    )

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )

        return ExtractorResult(rows=rows, warnings=warnings)
