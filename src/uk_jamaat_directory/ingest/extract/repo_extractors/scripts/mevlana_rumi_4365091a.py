from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
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
    key = "mevlana_rumi_4365091a"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("rumimosque.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://rumimosque.uk/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("prayer", "jam")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "zuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        dpt = None
        for t in tables:
            low = " ".join(" ".join(row) for row in (t.rows or []) if row).lower()
            if "prayer" in low and "jam" in low:
                dpt = t
                break
        if dpt is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable table not found",
            )
        # Find date in header cell, e.g. "London, UK, June 12, 2026 26 Dhū al-Hijjah 1447"
        date_text = ""
        for row in dpt.rows[:3]:
            for cell in row or []:
                cl = (cell or "").lower()
                if any(
                    m in cl
                    for m in (
                        "jan",
                        "feb",
                        "mar",
                        "apr",
                        "may",
                        "jun",
                        "jul",
                        "aug",
                        "sep",
                        "oct",
                        "nov",
                        "dec",
                    )
                ):
                    date_text = cell or ""
                    break
            if date_text:
                break
        parsed = parse_date_flexible(date_text, default_year=datetime.now().year)
        row_date = parsed or datetime.now().date()

        # Vertical table: collect Jamā‘ah (iqamah) values. Jumuah cell may contain "HH:MM | HH:MM"
        jamah_map: dict[Prayer, str] = {}
        jumuah_raw = ""
        for row in dpt.rows:
            if not row:
                continue
            label = (row[0] or "").strip().lower()
            # pick rightmost non-empty as the jamaat value (prefers Jamā‘ah col)
            raw_j = ""
            for c in reversed(row[1:]):
                if c and str(c).strip():
                    raw_j = str(c).strip()
                    break
            pr: Prayer | None = None
            if "fajr" in label:
                pr = Prayer.FAJR
            elif "zuhr" in label or "dhuhr" in label:
                pr = Prayer.DHUHR
            elif "asr" in label:
                pr = Prayer.ASR
            elif "maghrib" in label:
                pr = Prayer.MAGHRIB
            elif "isha" in label:
                pr = Prayer.ISHA
            elif "jumu" in label or "jumma" in label or "jumah" in label:
                jumuah_raw = raw_j
                continue
            if pr and raw_j:
                jamah_map[pr] = raw_j

        if not jamah_map:
            return ExtractorResult(rows=[], no_schedule_reason="no jamaat times found")

        # Build 1-row synthetic horizontal table for the daily prayers (Jumuah handled below)
        dstr = f"{row_date.day}/{row_date.month}/{row_date.year}"
        logical_header = ["date", "fajr", "zuhr", "asr", "maghrib", "isha"]
        data_row: list[str] = [dstr]
        for p in (Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA):
            data_row.append(jamah_map.get(p, ""))
        effective = html_helpers.Table([logical_header, data_row])
        res = self._extract_from_table(ctx, effective)

        # Emit Jumuah session rows from the Jumuah cell (one or more times separated by | or ;)
        if jumuah_raw:
            parts = re.split(r"\s*[|;]\s*", jumuah_raw)
            times: list = []
            for p in parts:
                p = (p or "").strip()
                if p:
                    jt = coerce_time(p, prayer=Prayer.JUMUAH.value)
                    if jt is not None:
                        times.append(jt)
            for idx, jt in enumerate(times, start=1):
                res.rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=Prayer.JUMUAH,
                        jamaat_time=jt,
                        start_time=None,
                        session_number=idx,
                        session_label=None,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label=self.target_label,
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"Jumuah {jumuah_raw}",
                            selector="jumuah cell",
                        ),
                    )
                )

        if not res.rows:
            return ExtractorResult(
                rows=[],
                warnings=res.warnings,
                no_schedule_reason="no extractable rows",
            )
        return res
