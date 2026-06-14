from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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
    key = "newbury_jamme_masjid_88ce3a6a"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("newburyjammemasjid.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.newburyjammemasjid.org.uk/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("prayer", "iqamah")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "zuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
    }

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        dpt = None
        for t in tables:
            low = " ".join(" ".join(r) for r in t.rows).lower()
            if "iqamah" in low or "jamah" in low or "begins" in low:
                dpt = t
                break
        if dpt is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable table not found",
            )
        # Build prayer -> raw jamaat (iqamah) from vertical rows
        jamah_map: dict[Prayer, str] = {}
        for row in dpt.rows:
            if not row:
                continue
            label = (row[0] or "").strip()
            pr = parse_prayer_label(label)
            if pr is None:
                for c in row[1:]:
                    pr = parse_prayer_label(c)
                    if pr is not None:
                        break
            if pr is None or pr == Prayer.JUMUAH:
                continue
            raw_j = ""
            for c in reversed(row[1:]):
                if c and c.strip():
                    raw_j = c.strip()
                    break
            if raw_j:
                jamah_map[pr] = raw_j
        if not jamah_map:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no jamaat times found",
            )
        date_text = ""
        for row in dpt.rows[:3]:
            for cell in row:
                cl = cell.lower()
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
                    date_text = cell
                    break
            if date_text:
                break
        parsed = parse_date_flexible(date_text, default_year=datetime.now().year)
        row_date = parsed or datetime.now().date()
        dstr = f"{row_date.day}/{row_date.month}/{row_date.year}"
        logical_header = ["date", "fajr", "zuhr", "asr", "maghrib", "isha"]
        data_row = [dstr]
        for p in (Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA):
            data_row.append(jamah_map.get(p, ""))
        effective = html_helpers.Table([logical_header, data_row])
        result = self._extract_from_table(ctx, effective)

        # Extract Jumuah times from separate text block
        warnings: list[ExtractorWarning] = list(result.warnings)
        ju_match = re.search(
            r"Jumma\s+Prayer.*?1st\s+jamath\s+at\s+(\d{1,2}:\d{2})[^0-9]*(\d{1,2}:\d{2})",
            html,
            re.I | re.S,
        )
        if ju_match:
            for session_num, raw in enumerate((ju_match.group(1), ju_match.group(2)), start=1):
                jt = coerce_time(raw, prayer="jumuah")
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} jumuah session {session_num}: {raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                win = PLAUSIBLE_WINDOWS.get("jumuah")
                if win and not (win[0] <= jt <= win[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{row_date} jumuah session {session_num}: {raw!r} outside plausible window",
                            target_label="timetable",
                        )
                    )
                    continue
                result.rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=Prayer.JUMUAH,
                        jamaat_time=jt,
                        timezone=ctx.timezone,
                        session_number=session_num,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=raw,
                            selector=f"Jumma Prayer session {session_num}",
                        ),
                    )
                )

        order = {
            Prayer.FAJR: 0,
            Prayer.DHUHR: 1,
            Prayer.ASR: 2,
            Prayer.MAGHRIB: 3,
            Prayer.ISHA: 4,
            Prayer.JUMUAH: 5,
        }
        result.rows.sort(key=lambda r: (r.date, order.get(r.prayer, 999), r.session_number))
        return result
