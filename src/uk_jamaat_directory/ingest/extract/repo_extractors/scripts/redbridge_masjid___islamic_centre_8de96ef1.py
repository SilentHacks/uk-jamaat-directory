from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
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
    key = "redbridge_masjid___islamic_centre_8de96ef1"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("redbridgeislamiccentre.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://redbridgeislamiccentre.co.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        text = html_helpers.html_to_text(html)
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []
        today = datetime.now().date()
        prayer_order = [Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA]
        tables = html_helpers.extract_tables(html)
        found_table = False
        for tbl in tables:
            hdr = [c.lower() for c in tbl.header]
            if "fajr" in " ".join(hdr) and "zuhr" in " ".join(hdr) and "magrib" in " ".join(hdr):
                found_table = True
                jama_row = None
                for r in tbl.body():
                    if r and r[0] and "jama" in r[0].lower():
                        jama_row = r
                        break
                if jama_row:
                    vals = jama_row[1:6]
                    for p, v in zip(prayer_order, vals, strict=True):
                        if not v:
                            continue
                        jt = coerce_time(v, prayer=p.value)
                        if jt is None:
                            warnings.append(
                                ExtractorWarning(
                                    code="unparseable_time",
                                    message=f"{today} {p.value}: {v!r}",
                                    target_label="timetable",
                                )
                            )
                            continue
                        win = PLAUSIBLE_WINDOWS.get(p.value)
                        if win and not (win[0] <= jt <= win[1]):
                            warnings.append(
                                ExtractorWarning(
                                    code="implausible_time",
                                    message=f"{today} {p.value}: {v!r} outside plausible window",
                                    target_label="timetable",
                                )
                            )
                            continue
                        rows.append(
                            ExtractorRow(
                                date=today,
                                prayer=p,
                                jamaat_time=jt,
                                timezone=ctx.timezone,
                                evidence=ctx.evidence(
                                    target_label="timetable",
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    raw_text=v,
                                    selector="jamaah_row",
                                ),
                            )
                        )
                break
        if not found_table:
            m = re.search(
                r"(?i)Jama['’]?\s*ah\s+(\d{1,2}[:.]\d{2})\s+(\d{1,2}[:.]\d{2})\s+(\d{1,2}[:.]\d{2})\s+(\d{1,2}[:.]\d{2})\s+(\d{1,2}[:.]\d{2})",
                text,
            )
            if m:
                vals = [m.group(i) for i in range(1, 6)]
                for p, v in zip(prayer_order, vals, strict=True):
                    jt = coerce_time(v.replace(".", ":"), prayer=p.value)
                    if jt is None:
                        continue
                    win = PLAUSIBLE_WINDOWS.get(p.value)
                    if win and not (win[0] <= jt <= win[1]):
                        continue
                    rows.append(
                        ExtractorRow(
                            date=today,
                            prayer=p,
                            jamaat_time=jt,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=v,
                                selector="jamaah_text",
                            ),
                        )
                    )
        if today.weekday() == 4:
            jumuah_times: list[str] = []
            for m in re.finditer(
                r"(?i)(?:\d+st|\d+nd)\s*Jama['’]?\s*ah[^0-9]*?(\d{1,2}[:.]\d{2}\s*(?:am|pm)?)",
                text,
            ):
                jumuah_times.append(m.group(1))
            if len(jumuah_times) < 2:
                jm = re.search(
                    r"(?i)Jumu['’]?ah[^0-9]*?(\d{1,2}[:.]\d{2}\s*(?:am|pm)?)[^0-9]*?(\d{1,2}[:.]\d{2}\s*(?:am|pm)?)",
                    text,
                )
                if jm:
                    jumuah_times = [jm.group(1), jm.group(2)]
            for idx, raw in enumerate(jumuah_times[:2], start=1):
                jt = coerce_time(raw.replace(".", ":"), prayer="jumuah")
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{today} jumuah: {raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                win = PLAUSIBLE_WINDOWS.get("jumuah")
                if win and not (win[0] <= jt <= win[1]):
                    continue
                rows.append(
                    ExtractorRow(
                        date=today,
                        prayer=Prayer.JUMUAH,
                        jamaat_time=jt,
                        session_number=idx,
                        session_label=f"session {idx}",
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=raw,
                            selector="jumuah_blurb",
                        ),
                    )
                )
        seen = set()
        deduped: list[ExtractorRow] = []
        for r in rows:
            k = (r.date, r.prayer, getattr(r, "session_number", 1))
            if k in seen:
                continue
            seen.add(k)
            deduped.append(r)
        rows = deduped
        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
