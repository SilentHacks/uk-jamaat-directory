from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS, coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractorResult,
    ExtractorRow,
    ExtractorWarning,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    TableTimetableExtractor,
)


class Extractor(TableTimetableExtractor):
    key = "madina_foundation_dagenham_east_islamic_centre_6301b29c"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("madinafoundationdagenham.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://madinafoundationdagenham.org/mobile",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        dpt = None
        for t in tables:
            if t.rows and t.rows[0] and "prayer" in str(t.rows[0][0] or "").lower():
                dpt = t
                break
        if dpt is None:
            for t in tables:
                joined = " ".join(" ".join(str(c or "") for c in (r or [])) for r in t.rows).lower()
                if ("iqamah" in joined or "jamah" in joined) and len(t.rows) >= 6:
                    dpt = t
                    break
        if dpt is None:
            for t in tables:
                joined = " ".join(" ".join(str(c or "") for c in (r or [])) for r in t.rows).lower()
                if "iqamah" in joined or "jamah" in joined:
                    dpt = t
                    break
        if dpt is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable table not found",
            )
        today = datetime.now().date()
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        for r in dpt.rows:
            if not r:
                continue
            label = (r[0] or "").strip()
            pr = parse_prayer_label(label)
            if pr is None:
                continue
            if pr == Prayer.JUMUAH:
                raw = ""
                for c in r[1:]:
                    if c and any(ch.isdigit() for ch in c):
                        raw = c
                        break
                parts = re.split(r"\s*\|\s*", raw.strip()) if raw else []
                for idx, p in enumerate(parts, start=1):
                    jt = coerce_time(p, prayer="jumuah")
                    if jt is None:
                        warnings.append(
                            ExtractorWarning(
                                code="unparseable_time",
                                message=f"{today} jumuah session {idx}: {p!r}",
                                target_label=self.target_label,
                            )
                        )
                        continue
                    win = PLAUSIBLE_WINDOWS.get("jumuah")
                    if win and not (win[0] <= jt <= win[1]):
                        warnings.append(
                            ExtractorWarning(
                                code="implausible_time",
                                message=(
                                    f"{today} jumuah session {idx}: {p!r} outside plausible window"
                                ),
                                target_label=self.target_label,
                            )
                        )
                        continue
                    rows.append(
                        ExtractorRow(
                            date=today,
                            prayer=Prayer.JUMUAH,
                            jamaat_time=jt,
                            start_time=None,
                            session_number=idx,
                            session_label=f"session {idx}",
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label=self.target_label,
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=raw or p,
                                selector="Jumuah row",
                            ),
                        )
                    )
                continue

            begins = None
            iq = None
            times_found = []
            for c in r[1:]:
                tc = coerce_time(c, prayer=pr.value)
                if tc is not None:
                    times_found.append((c, tc))
            if times_found:
                begins = times_found[0][1] if len(times_found) >= 1 else None
                iq = times_found[-1][1] if times_found else None
            if iq is None:
                for c in reversed(r[1:]):
                    if c and any(ch.isdigit() for ch in c):
                        iq = coerce_time(c, prayer=pr.value)
                        break
            if iq is None:
                continue
            win = PLAUSIBLE_WINDOWS.get(pr.value)
            if win and not (win[0] <= iq <= win[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"{today} {pr.value}: {iq} outside window",
                        target_label=self.target_label,
                    )
                )
                continue
            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=pr,
                    jamaat_time=iq,
                    start_time=begins,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label=self.target_label,
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join([str(x or "") for x in r]),
                        selector="dsPrayerTimetable row",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no jamaat times found",
            )
        order = {
            Prayer.FAJR: 0,
            Prayer.DHUHR: 1,
            Prayer.ASR: 2,
            Prayer.MAGHRIB: 3,
            Prayer.ISHA: 4,
            Prayer.JUMUAH: 5,
        }
        rows.sort(key=lambda r: (order.get(r.prayer, 99), r.session_number))
        return ExtractorResult(rows=rows, warnings=warnings)
