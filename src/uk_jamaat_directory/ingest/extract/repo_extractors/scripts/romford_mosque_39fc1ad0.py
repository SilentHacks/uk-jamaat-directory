import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.html import html_to_text
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

# Accept either:
# "Friday, June 12, 2026" or "Friday, June 12, 2026 • 26 Dhul Hijjah 1447"
# The live rendered text contains this near "Prayer Times".
# Tolerant date header for the inline timetable text on this site.
# Observed live (after html_to_text): "Friday, June 12, 2026 • 26 Dhul Hijjah 1447"
# and repeated blocks with "Prayer Times Friday, June 12, 2026 26 Dhul Hijjah 1447".
# Also tolerate minor rendering differences and glued prefixes (e.g. "Mosque Friday,").
_DATE_LINE_RE = re.compile(
    r"(?P<date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+"
    r"[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)

def _find_date_header(text: str):
    m = _DATE_LINE_RE.search(text)
    if m:
        return m
    # Very loose: any "Weekday, Monthname DD, YYYY" (case/punct tolerant), even if glued to prior word
    m = re.search(
        r"([A-Za-z]{6,9},\s+[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
        text,
        re.IGNORECASE,
    )
    if m:
        # adapt to .group("date") expected by caller
        class _Fake:
            def __init__(self, val: str):
                self._val = val
            def group(self, key):
                if key in (0, 1, "date"):
                    return self._val
                return None
        return _Fake(m.group(1))
    return None

# Map labels we see in the rendered text to (Prayer, optional jumuah session number).
# Only JAMAAT (second time value) is used. We ignore Shuruq and Athan columns.
_LABEL_MAP = {
    "fajr": (Prayer.FAJR, None),
    "zuhr": (Prayer.DHUHR, None),
    "dhuhr": (Prayer.DHUHR, None),
    "asr": (Prayer.ASR, None),
    "maghrib": (Prayer.MAGHRIB, None),
    "isha": (Prayer.ISHA, None),
    "jumuah 1": (Prayer.JUMUAH, 1),
    "jumuah 2": (Prayer.JUMUAH, 2),
    "jummah 1": (Prayer.JUMUAH, 1),
    "jummah 2": (Prayer.JUMUAH, 2),
    "jumua 1": (Prayer.JUMUAH, 1),
    "jumua 2": (Prayer.JUMUAH, 2),
}


class Extractor(BaseMosqueWebsiteExtractor):
    key = "romford_mosque_39fc1ad0"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("romfordmosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        self._targets = (
            TargetSpec(
                label="timetable",
                url="http://romfordmosque.co.uk/",
                kind=TargetKind.RENDERED_HTML,
                requires_javascript=True,
            ),
        )
        super().__init__()

    @property
    def targets(self):
        return self._targets

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        text = html_to_text(artifact.text())
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        # The page may list "Prayer Times" followed by the date header.
        # Search the whole text; the first match is sufficient (today + visible Jumuah).
        date_match = _find_date_header(text)
        if not date_match:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no date header found in timetable text",
            )

        ds = date_match.group("date") if hasattr(date_match, "group") else str(date_match)
        row_date = parse_date_flexible(ds, default_year=datetime.now().year)
        if row_date is None:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="could not parse date header",
            )

        # Window after the date header should contain the Athan/Iqamah block for that day.
        try:
            start = date_match.end()  # type: ignore[attr-defined]
        except Exception:
            # fallback when using a shim object
            start = text.lower().find(ds.lower())
            if start < 0:
                start = 0
        window = text[start : start + 3000]

        # Walk tokens and collect label + up to two time-like tokens.
        # We take the second time (iqamah/jamaat). Jumuah may appear as two sessions.
        seen: set[tuple] = set()
        tokens = re.split(r"\s+", window)
        i = 0
        n = len(tokens)
        while i < n:
            # build a 1- or 2-word label
            t0 = tokens[i].strip().rstrip(":").lower()
            if not t0 or t0 in {"athan", "iqamah", "am", "pm", "•"}:
                i += 1
                continue
            t1 = None
            if i + 1 < n:
                cand = tokens[i + 1].strip().rstrip(":").lower()
                if cand and not re.match(r"^\d{1,2}[:.]?\d{0,2}$", cand) and cand not in {"athan", "iqamah", "am", "pm"}:
                    t1 = cand
            label = f"{t0} {t1}".strip() if t1 else t0
            mapped = _LABEL_MAP.get(label) or _LABEL_MAP.get(t0)
            if mapped is None:
                i += 1
                continue

            prayer, session = mapped

            # Collect up to two time-like tokens after the label (athan, iqamah).
            j = i + (2 if t1 else 1)
            times: list[str] = []
            while j < n and len(times) < 2:
                tk = tokens[j].strip()
                if not tk or tk in {"athan", "iqamah", "am", "pm", "•"}:
                    j += 1
                    continue
                if tk in {"--", "-"} or re.match(r"^\d{1,2}[:.]?\d{2}$", tk) or re.match(r"^\d{1,2}[:.]?\d{2}(?:am|pm)$", tk, re.I):
                    times.append(tk)
                    j += 1
                    continue
                # next label-like token -> stop
                if re.match(r"^[a-z]", tk, re.I):
                    break
                j += 1

            raw_iq = ""
            if len(times) >= 2:
                raw_iq = times[1]
            elif len(times) == 1:
                raw_iq = times[0]

            if raw_iq and raw_iq not in {"--", "-"}:
                jt = coerce_time(raw_iq, prayer=prayer.value)
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}{f' session {session}' if session else ''}: {raw_iq!r}",
                            target_label="timetable",
                        )
                    )
                else:
                    key = (row_date, prayer, session or 1)
                    if key not in seen:
                        seen.add(key)
                        rows.append(
                            ExtractorRow(
                                date=row_date,
                                prayer=prayer,
                                jamaat_time=jt,
                                session_number=session or 1,
                                session_label=(f"Jumuah {session}" if session else None),
                                timezone=ctx.timezone,
                                evidence=ctx.evidence(
                                    target_label="timetable",
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    raw_text=f"{label} {raw_iq}",
                                    selector="rendered text block",
                                ),
                            )
                        )
            i = j if j > i else (i + 1)

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable jamaat rows",
            )
        return ExtractorResult(rows=rows, warnings=warnings)
