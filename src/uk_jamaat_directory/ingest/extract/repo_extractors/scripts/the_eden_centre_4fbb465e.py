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


def _double_unescape_js(s: str) -> str:
    """Apply the double backslash unescape typical of NEXT.js chunk strings.
    Turns  \\"  into "  and  \\\\  into \\ , repeatedly until stable.
    """
    prev = None
    out = s
    while prev != out:
        prev = out
        out = out.replace("\\\\", "\\").replace('\\"', '"')
    return out


def _find_timetable_objects(text: str) -> list[dict]:
    """Find objects that look like {..., "days": [ {..jamaatFajr..}, ... ] } even when
    they are serialized inside JS string literals (\\"-escaped).
    Strategy:
      1) Look for tokens like highfieldsTimetable":{  or any *Timetable":{
         then balance the { ... } and double-unescape the captured body to get real JSON.
      2) Also scan for any balanced "days":[ ... ] that contain a jamaatFajr sample,
         double-unescape the array text and treat the recovered array as the days.
    Returns a list of container dicts that have at least a "days" key with content.
    """
    containers: list[dict] = []

    # --- 1) *Timetable" : { ... } style (the live shape we observed)
    # The object lives inside a JS string literal, so the " after the key is written as \\"
    # e.g.  highfieldsTimetable\\":{\\"_id\\":... \\"days\\":[...]
    for m in re.finditer(r"[A-Za-z0-9_]*[Tt]imetable\\+\"?\s*:\s*\{", text):
        start = text.find("{", m.start())
        if start == -1:
            continue
        depth = 0
        end = start
        for i in range(start, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        raw = text[start:end]
        un = _double_unescape_js(raw)
        try:
            obj = json.loads(un)
            if isinstance(obj, dict) and isinstance(obj.get("days"), list):
                containers.append(obj)
        except Exception:
            continue

    # --- 2) direct "days":[...] arrays anywhere (possibly still escaped) ---
    for m in re.finditer(r"\"days\"\s*:\s*\[", text):
        start = text.find("[", m.start())
        if start == -1:
            continue
        depth = 0
        end = start
        for i in range(start, len(text)):
            c = text[i]
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        arr_text = text[start:end]
        un = _double_unescape_js(arr_text)
        try:
            arr = json.loads(un)
            if isinstance(arr, list):
                sample = next((x for x in arr if isinstance(x, dict) and "jamaatFajr" in x), None)
                if sample:
                    # fabricate a lightweight container
                    pre = text[max(0, m.start() - 1500) : m.start()]
                    my = re.search(r"\"parsedYear\"\s*:\s*(\d{4})", pre)
                    mm = re.search(r"\"parsedMonth\"\s*:\s*(\d{1,2})", pre)
                    ctitle = re.search(r"\"title\"\s*:\s*\"([^\"]+)\"", pre)
                    ccentre = re.search(r"\"centre\"\s*:\s*\"([^\"]+)\"", pre)
                    container: dict = {"days": [x for x in arr if isinstance(x, dict)]}
                    if my:
                        container["parsedYear"] = int(my.group(1))
                    if mm:
                        container["parsedMonth"] = int(mm.group(1))
                    if ctitle:
                        container["title"] = ctitle.group(1)
                    if ccentre:
                        container["centre"] = ccentre.group(1)
                    containers.append(container)
        except Exception:
            continue

    # Dedup by identity of the days list head
    seen = set()
    out: list[dict] = []
    for c in containers:
        days = c.get("days") or []
        if not days:
            continue
        key = (len(days), (days[0].get("jamaatFajr") if days else None))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _pick_best_container(containers: list[dict]) -> dict | None:
    if not containers:
        return None
    # Prefer anything mentioning highfields and having a long month
    for c in containers:
        blob = " ".join(str(v) for v in (c.get("title"), c.get("centre"), c.get("_id"), "")).lower()
        if "highfield" in blob and len(c.get("days") or []) >= 20:
            return c
    # Any reasonably complete month
    for c in containers:
        if len(c.get("days") or []) >= 20:
            return c
    return containers[0]


class Extractor(BaseMosqueWebsiteExtractor):
    key = "the_eden_centre_4fbb465e"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("theedenfoundation.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://theedenfoundation.org.uk/prayer-times",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        text = artifact.text()
        containers = _find_timetable_objects(text)
        picked = _pick_best_container(containers)
        if picked is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no embedded monthly jamaat timetable found",
            )

        days = picked.get("days") or []
        year = picked.get("parsedYear") or datetime.now().year
        month = picked.get("parsedMonth") or datetime.now().month

        prayer_map = {
            "jamaatFajr": Prayer.FAJR,
            "jamaatZuhr": Prayer.DHUHR,
            "jamaatAsr": Prayer.ASR,
            "jamaatMaghrib": Prayer.MAGHRIB,
            "jamaatIsha": Prayer.ISHA,
        }

        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        for idx, day in enumerate(days, start=1):
            daynum = day.get("date")
            if not isinstance(daynum, int):
                continue
            try:
                row_date = date(year, month, daynum)
            except ValueError:
                continue

            for key, prayer in prayer_map.items():
                raw = day.get(key)
                if not raw or not isinstance(raw, str):
                    continue
                jt = coerce_time(raw, prayer=prayer.value)
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {raw!r}",
                            target_label="timetable",
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
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=json.dumps(
                                {k: day.get(k) for k in ("date", key)}, separators=(",", ":")
                            ),
                            selector=f"days[{idx}] {key}",
                        ),
                    )
                )

            # Jumu'ah on Fridays if present (single session per current data shape)
            if day.get("isFriday") and day.get("jumuah"):
                raw_j = day.get("jumuah")
                if isinstance(raw_j, str) and raw_j.strip():
                    jt = coerce_time(raw_j, prayer="jumuah")
                    if jt is None:
                        warnings.append(
                            ExtractorWarning(
                                code="unparseable_time",
                                message=f"{row_date} jumuah: {raw_j!r}",
                                target_label="timetable",
                            )
                        )
                    else:
                        rows.append(
                            ExtractorRow(
                                date=row_date,
                                prayer=Prayer.JUMUAH,
                                jamaat_time=jt,
                                session_number=1,
                                timezone=ctx.timezone,
                                evidence=ctx.evidence(
                                    target_label="timetable",
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    raw_text=json.dumps(
                                        {"date": day.get("date"), "jumuah": raw_j},
                                        separators=(",", ":"),
                                    ),
                                    selector=f"days[{idx}] jumuah",
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
