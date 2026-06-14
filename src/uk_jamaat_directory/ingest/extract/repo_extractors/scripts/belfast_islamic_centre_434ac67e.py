from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.html import (
    Table,
    extract_tables,
    header_matches,
    normalize_whitespace,
)
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
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
    key = "belfast_islamic_centre_434ac67e"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("belfastislamiccentre.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://belfastislamiccentre.org.uk/",
            kind=TargetKind.HTML,
        ),
    )
    target_label = "timetable"

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = extract_tables(html)

        # DPT plugin: first row is date, second is headers, rest is data
        matching_table = None
        date_cell = None
        for table in tables:
            if len(table.rows) > 1:
                header_row = table.rows[1]
                if header_matches(header_row, ["prayer", "begins", "iqamah"]):
                    date_cell = table.rows[0][0] if table.rows[0] else None
                    matching_table = Table([header_row] + table.rows[2:])
                    break

        if matching_table is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable table not found",
            )

        # Parse date from first row
        row_date = None
        if date_cell:
            row_date = parse_date_flexible(
                normalize_whitespace(date_cell), default_year=datetime.now().year
            )

        if row_date is None:
            row_date = datetime.now().date()

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        for row_idx, row in enumerate(matching_table.body(), start=1):
            if len(row) < 3:
                continue

            prayer_label = normalize_whitespace(row[0])
            prayer = parse_prayer_label(prayer_label)
            if prayer is None:
                continue

            # Column 1 is "Begins" (adhan), Column 2 is "Iqamah" (jamaat)
            jamaat_str = normalize_whitespace(row[2])
            if not jamaat_str:
                continue

            jamaat_time = coerce_time(jamaat_str, prayer=prayer.value)
            if jamaat_time is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{prayer.value}: {jamaat_str!r}",
                        target_label=self.target_label,
                    )
                )
                continue

            start_str = normalize_whitespace(row[1])
            start_time = coerce_time(start_str, prayer=prayer.value) if start_str else None

            session_number = 1
            session_label = None
            if prayer.value == "jumuah":
                sessions_today = [
                    r
                    for r in rows
                    if r.date == row_date and r.prayer.value == "jumuah"
                ]
                session_number = len(sessions_today) + 1
                session_label = f"session {session_number}"

            evidence = ctx.evidence(
                target_label=self.target_label,
                extractor_key=self.key,
                extractor_version=self.version,
                raw_text=" | ".join(row),
                selector=f"table row {row_idx}",
            )

            rows.append(
                ExtractorRow(
                    date=row_date,
                    prayer=prayer,
                    jamaat_time=jamaat_time,
                    start_time=start_time,
                    session_number=session_number,
                    session_label=session_label,
                    timezone=ctx.timezone,
                    evidence=evidence,
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )

        return ExtractorResult(rows=rows, warnings=warnings)
