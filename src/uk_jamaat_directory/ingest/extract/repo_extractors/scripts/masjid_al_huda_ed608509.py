from __future__ import annotations

import json
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
    key = "masjid_al_huda_ed608509"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("alhudabolton.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://alhudabolton.com/?rest_route=/dpt/v1/prayertime&filter=today",
            kind=TargetKind.JSON,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        try:
            payload = json.loads(artifact.text())
        except Exception:
            return ExtractorResult(rows=[], no_schedule_reason="invalid json")
        data = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(data, dict):
            return ExtractorResult(rows=[], no_schedule_reason="no schedule data")
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        def add_row(d: dict, key: str, prayer: Prayer) -> None:
            raw = d.get(key)
            if not raw:
                return
            if isinstance(raw, str) and ":" in raw:
                parts = raw.split(":")[:2]
                raw = ":".join(parts)
            jt = coerce_time(str(raw), prayer=prayer.value)
            if jt is None:
                return
            win = PLAUSIBLE_WINDOWS.get(prayer.value)
            if win and not (win[0] <= jt <= win[1]):
                return
            ddate = d.get("d_date")
            try:
                row_date = date.fromisoformat(str(ddate)) if ddate else datetime.now().date()
            except Exception:
                row_date = datetime.now().date()
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
                        raw_text=str(raw),
                        selector=key,
                    ),
                )
            )

        add_row(data, "fajr_jamah", Prayer.FAJR)
        add_row(data, "zuhr_jamah", Prayer.DHUHR)
        add_row(data, "asr_jamah", Prayer.ASR)
        add_row(data, "maghrib_jamah", Prayer.MAGHRIB)
        add_row(data, "isha_jamah", Prayer.ISHA)

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
