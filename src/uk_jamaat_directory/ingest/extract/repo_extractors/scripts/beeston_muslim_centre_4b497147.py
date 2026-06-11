from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
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
    key = "beeston_muslim_centre_4b497147"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("beestonmuslimcentre.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://beestonmuslimcentre.co.uk/prayer-time/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        tables = extract_tables(artifact.text())
        if not tables:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no tables found",
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no tables found in page",
                        target_label="timetable",
                    )
                ],
            )

        target_table = None
        for table in tables:
            rows_list = table.rows
            if len(rows_list) < 2:
                continue
            # Check if second row has "date" keyword
            second_row = rows_list[1]
            second_row_lower = [cell.lower() for cell in second_row]
            if any("date" in cell for cell in second_row_lower):
                target_table = table
                break

        if target_table is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable table not found",
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no table with date column in second row",
                        target_label="timetable",
                    )
                ],
            )

        # Use second row as header (first row has prayer names)
        header = [cell.strip() for cell in target_table.rows[1]]
        body = [
            [cell.strip() for cell in row]
            for row in target_table.rows[2:]
        ]

        date_idx = None
        for idx, cell in enumerate(header):
            if "date" in cell.lower():
                date_idx = idx
                break

        if date_idx is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="date column not found",
                warnings=[
                    ExtractorWarning(
                        code="no_date_column",
                        message=f"date column not found in header: {header}",
                        target_label="timetable",
                    )
                ],
            )

        prayer_columns = {
            Prayer.FAJR: 3,
            Prayer.DHUHR: 6,
            Prayer.ASR: 8,
            Prayer.MAGHRIB: 10,
            Prayer.ISHA: 12,
        }

        rows: list[ExtractorRow] = []
        year = datetime.now().year

        for row_number, row in enumerate(body, start=3):
            if date_idx >= len(row):
                continue

            raw_date = row[date_idx].strip()
            if not raw_date:
                continue

            parsed_date = parse_date_flexible(raw_date, default_year=year)
            if parsed_date is None:
                continue

            for prayer, col_idx in prayer_columns.items():
                if col_idx >= len(row):
                    continue

                raw_time = row[col_idx].strip()
                if not raw_time:
                    continue

                jamaat = coerce_time(raw_time, prayer=prayer.value)
                if jamaat is None:
                    continue

                window = PLAUSIBLE_WINDOWS.get(prayer.value)
                if window and not (window[0] <= jamaat <= window[1]):
                    continue

                rows.append(
                    ExtractorRow(
                        date=parsed_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(row),
                            selector=f"table row {row_number}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no extractable rows",
            )

        return ExtractorResult(rows=rows)
