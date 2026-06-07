from __future__ import annotations

from datetime import date

from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
from uk_jamaat_directory.ingest.extract.helpers.relative import (
    add_minutes,
    parse_offset_minutes,
)
from uk_jamaat_directory.ingest.extract.helpers.times import parse_time_loose
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

SYNTHETIC_FIXTURE = """<!doctype html>
<html><body>
<table>
  <tr><th>Date</th><th>Prayer</th><th>Adhan</th><th>Jamaat</th></tr>
  <tr><td>2026-06-08</td><td>Fajr</td><td>03:30</td><td>04:00</td></tr>
  <tr><td>2026-06-08</td><td>Dhuhr</td><td>13:00</td><td>13:30</td></tr>
  <tr><td>2026-06-08</td><td>Asr</td><td>17:30</td><td>18:00</td></tr>
  <tr><td>2026-06-08</td><td>Maghrib</td><td>21:15</td><td>5 minutes</td></tr>
  <tr><td>2026-06-08</td><td>Isha</td><td>22:30</td><td>23:00</td></tr>
  <tr><td>2026-06-12</td><td>Jumuah</td><td>13:00</td><td>13:30</td></tr>
  <tr><td>2026-06-12</td><td>Jumuah</td><td>14:00</td><td>14:30</td></tr>
</table>
</body></html>
"""


class Extractor(BaseMosqueWebsiteExtractor):
    key = "synthetic_html_table"
    version = "2026.06.08.1"

    source_match = SourceMatch(domains=("synthetic.example",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://synthetic.example/prayer-timetable",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        body = ctx.artifact("timetable")
        if not body.body:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="empty_artifact",
                        message="timetable artifact is empty",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="artifact was empty",
            )
        html = body.text()
        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="timetable artifact did not contain a table",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no table present",
            )
        table = tables[0]
        rows = list(table.body())
        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_rows",
                        message="timetable table was empty",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no rows present",
            )

        extracted_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        for row_index, row in enumerate(rows, start=1):
            if len(row) < 4:
                warnings.append(
                    ExtractorWarning(
                        code="short_row",
                        message=f"row {row_index} has fewer than 4 columns",
                        target_label="timetable",
                    )
                )
                continue
            try:
                parsed_date = date.fromisoformat(row[0])
            except ValueError:
                warnings.append(
                    ExtractorWarning(
                        code="bad_date",
                        message=f"row {row_index} has invalid date '{row[0]}'",
                        target_label="timetable",
                    )
                )
                continue
            prayer = parse_prayer_label(row[1])
            if prayer is None:
                warnings.append(
                    ExtractorWarning(
                        code="unknown_prayer",
                        message=f"row {row_index} has unknown prayer '{row[1]}'",
                        target_label="timetable",
                    )
                )
                continue
            start_time = parse_time_loose(row[2])
            jamaat_value = row[3].strip()
            jamaat_time = parse_time_loose(jamaat_value)
            derivation: dict[str, object] | None = None
            if jamaat_time is None:
                offset = parse_offset_minutes(jamaat_value)
                if offset is not None and start_time is not None:
                    jamaat_time = add_minutes(start_time, offset)
                    derivation = {
                        "type": "relative_offset",
                        "base": "start_time",
                        "offset_minutes": offset,
                        "source_text": jamaat_value,
                    }
            if jamaat_time is None:
                warnings.append(
                    ExtractorWarning(
                        code="bad_jamaat",
                        message=f"row {row_index} has invalid jamaat time '{row[3]}'",
                        target_label="timetable",
                    )
                )
                continue

            session_number = 1
            session_label: str | None = None
            if prayer.value == "jumuah":
                sessions_today = [
                    r
                    for r in extracted_rows
                    if r.date == parsed_date and r.prayer.value == "jumuah"
                ]
                session_number = len(sessions_today) + 1
                session_label = f"session {session_number}"

            evidence = ctx.evidence(
                target_label="timetable",
                extractor_key=self.key,
                extractor_version=self.version,
                raw_text=" | ".join(row),
                selector=f"table tbody tr:nth-child({row_index + 1})",
                derivation=derivation,
            )
            extracted_rows.append(
                ExtractorRow(
                    date=parsed_date,
                    prayer=prayer,
                    jamaat_time=jamaat_time,
                    start_time=start_time,
                    session_number=session_number,
                    session_label=session_label,
                    timezone=ctx.timezone,
                    evidence=evidence,
                )
            )

        if not extracted_rows and not warnings:
            warnings.append(
                ExtractorWarning(
                    code="no_extractable_rows",
                    message="table parsed but no rows were extractable",
                    target_label="timetable",
                )
            )
        return ExtractorResult(rows=extracted_rows, warnings=warnings)
