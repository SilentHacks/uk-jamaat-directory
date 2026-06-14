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
    key = "lammack_prayer_room_f51855a6"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("lammack.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://lammack.org/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        m = re.search(r'wire:snapshot="([^"]*)"', html)
        if not m:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no livewire snapshot found",
            )

        raw = m.group(1)
        raw = (
            raw.replace("&quot;", '"')
            .replace("&amp;", "&")
            .replace("&#039;", "'")
            .replace("&#x27;", "'")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
        )
        try:
            snap = json.loads(raw)
        except Exception as exc:
            warnings.append(
                ExtractorWarning(
                    code="json_parse_error",
                    message=str(exc),
                    target_label="timetable",
                )
            )
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="failed to parse snapshot json",
            )

        def _find_day_blocks(obj: object, blocks: list[dict]) -> None:
            if isinstance(obj, dict):
                if "name" in obj and "times" in obj and isinstance(obj.get("times"), list):
                    blocks.append(obj)
                for v in obj.values():
                    _find_day_blocks(v, blocks)
            elif isinstance(obj, list):
                for it in obj:
                    _find_day_blocks(it, blocks)

        day_blocks: list[dict] = []
        _find_day_blocks(snap, day_blocks)

        prayer_map: dict[str, Prayer] = {
            "Fajr": Prayer.FAJR,
            "Zohr": Prayer.DHUHR,
            "Asr": Prayer.ASR,
            "Maghrib": Prayer.MAGHRIB,
            "Isha": Prayer.ISHA,
            "Jumuah": Prayer.JUMUAH,
        }

        for block in day_blocks:
            dval = block.get("date")
            row_date: date | None = None
            if isinstance(dval, list) and dval and isinstance(dval[0], str):
                iso = dval[0]
                try:
                    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                    row_date = dt.date()
                except Exception:
                    pass
            if row_date is None:
                continue

            times_list = block.get("times") or []
            for tentry in times_list:
                if not isinstance(tentry, dict):
                    continue
                for pname, jlist in tentry.items():
                    if pname not in prayer_map:
                        continue
                    prayer = prayer_map[pname]
                    if not isinstance(jlist, list):
                        continue
                    for entry in jlist:
                        if not isinstance(entry, dict):
                            continue
                        jraw = entry.get("jamaat")
                        if jraw is None:
                            continue
                        jstr = str(jraw).strip()
                        if not jstr or jstr == "-":
                            continue
                        jt = coerce_time(jstr, prayer=prayer.value)
                        if jt is None:
                            warnings.append(
                                ExtractorWarning(
                                    code="unparseable_time",
                                    message=f"{row_date} {prayer.value}: {jstr!r}",
                                    target_label="timetable",
                                )
                            )
                            continue
                        window = PLAUSIBLE_WINDOWS.get(prayer.value)
                        if window and not (window[0] <= jt <= window[1]):
                            warnings.append(
                                ExtractorWarning(
                                    code="implausible_time",
                                    message=f"{row_date} {prayer.value}: {jstr!r} outside plausible window",
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
                                    raw_text=f"{pname} jamaat {jstr}",
                                    selector="livewire snapshot",
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
