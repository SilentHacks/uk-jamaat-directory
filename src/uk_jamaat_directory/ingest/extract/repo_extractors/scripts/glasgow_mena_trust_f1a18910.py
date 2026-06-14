from __future__ import annotations

from datetime import date

from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
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


class Extractor(BaseMosqueWebsiteExtractor):
    key = "glasgow_mena_trust_f1a18910"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("menatrust.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.menatrust.org.uk/salahtimes/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no table found in timetable",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        table = tables[0]
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        # Today's date for all entries
        today = date.today()

        for row_index, row in enumerate(table.body(), start=1):
            if len(row) < 3:
                continue

            prayer_text = row[0].strip().lower()
            if prayer_text == "sunrise":
                continue

            prayer = parse_prayer_label(prayer_text)
            if prayer is None:
                continue

            jamaat_cell = row[2].strip() if len(row) > 2 else ""
            if not jamaat_cell:
                continue

            jamaat_time = parse_time_loose(jamaat_cell)
            if jamaat_time is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"row {row_index} {prayer.value}: {jamaat_cell!r}",
                        target_label="timetable",
                    )
                )
                continue

            # Handle multiple Jumuah sessions
            session_number = 1
            session_label: str | None = None
            if prayer.value == "jumuah":
                sessions_today = [r for r in rows if r.date == today and r.prayer.value == "jumuah"]
                session_number = len(sessions_today) + 1
                session_label = f"session {session_number}"

            evidence = ctx.evidence(
                target_label="timetable",
                extractor_key=self.key,
                extractor_version=self.version,
                raw_text=" | ".join(row),
                selector=f"table tr:nth-child({row_index + 1})",
            )

            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=jamaat_time,
                    session_number=session_number,
                    session_label=session_label,
                    timezone=ctx.timezone,
                    evidence=evidence,
                )
            )

        if not rows and not warnings:
            warnings.append(
                ExtractorWarning(
                    code="no_extractable_rows",
                    message="table parsed but no rows were extractable",
                    target_label="timetable",
                )
            )

        return ExtractorResult(rows=rows, warnings=warnings)
