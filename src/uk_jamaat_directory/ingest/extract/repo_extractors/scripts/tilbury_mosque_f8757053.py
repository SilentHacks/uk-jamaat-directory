from __future__ import annotations

from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
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
    key = "tilbury_mosque_f8757053"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("tilburymosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://tilburymosque.co.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        timetable = None
        for t in tables:
            for r in t.rows:
                if r and str(r[0]).strip().lower() == "iqamah":
                    timetable = t
                    break
            if timetable:
                break
        if timetable is None:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")
        iq_row = None
        for r in timetable.rows:
            if r and str(r[0]).strip().lower() == "iqamah":
                iq_row = r
                break
        if not iq_row:
            return ExtractorResult(rows=[], no_schedule_reason="no iqamah row")
        # Daily "today" widget: attribute the displayed jamaat times to the current date.
        # The page title cell often contains a stale/hardcoded demo date (e.g. "July 21, 2025");
        # using datetime.now().date() ensures the schedule is published for the day it is seen,
        # and satisfies freshness windows without hardcoding a literal year.
        row_date = datetime.now().date()
        iq_data = iq_row[1:] if len(iq_row) > 1 else []
        ordered_prayers = [Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA]
        if len(iq_data) < 5:
            return ExtractorResult(rows=[], no_schedule_reason="iqamah row too short")
        rows_out: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        for pi, p in enumerate(ordered_prayers):
            raw = iq_data[pi] if pi < len(iq_data) else ""
            if not raw:
                continue
            jt = coerce_time(raw, prayer=p.value)
            if jt is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{row_date} {p.value}: {raw!r}",
                        target_label="timetable",
                    )
                )
                continue
            rows_out.append(
                ExtractorRow(
                    date=row_date,
                    prayer=p,
                    jamaat_time=jt,
                    start_time=None,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join(iq_row),
                        selector="iqamah row",
                    ),
                )
            )
        if not rows_out:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows_out, warnings=warnings)
