from datetime import datetime

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
    key = "faizan_e_islam_centre_c7d7d4ad"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("faizaneislam.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://faizaneislam.com/prayer-times/prayer-times-london/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = extract_tables(html)
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        # Find the monthly timetable: it has header row with prayer names
        # and second row with "Date", "Day", "Begins", "Jamaat" columns
        timetable = None
        for table in tables:
            if len(table.rows) < 2:
                continue
            second_row = table.rows[1]
            second_row_lower = [str(c).lower() for c in second_row]
            if "date" in second_row_lower and "jamaat" in second_row_lower:
                timetable = table
                break

        if not timetable:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="monthly timetable with Date and Jamaat columns not found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        # Extract column indices from the second header row
        second_row = timetable.rows[1]
        second_row_lower = [str(c).lower() for c in second_row]

        date_idx = None
        jamaat_indices = {}
        for i, cell in enumerate(second_row_lower):
            if "date" in cell:
                date_idx = i
            elif "jamaat" in cell:
                # Look back at the first row to find which prayer this is
                if i >= len(timetable.rows[0]):
                    continue
                prayer_header = str(timetable.rows[0][i]).lower()
                if "fajr" in prayer_header:
                    jamaat_indices[Prayer.FAJR] = i
                elif "zuhr" in prayer_header:
                    jamaat_indices[Prayer.DHUHR] = i
                elif "asr" in prayer_header:
                    jamaat_indices[Prayer.ASR] = i
                elif "maghrib" in prayer_header:
                    jamaat_indices[Prayer.MAGHRIB] = i
                elif "isha" in prayer_header:
                    jamaat_indices[Prayer.ISHA] = i

        if date_idx is None or not jamaat_indices:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="column_parse_error",
                        message=f"could not find date or jamaat columns in {second_row}",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="date or prayer columns not found",
            )

        # Parse data rows (starting from row 2)
        for row_num, row in enumerate(timetable.rows[2:], start=3):
            if not row or date_idx >= len(row):
                continue

            date_cell = str(row[date_idx]).strip()
            if not date_cell:
                continue

            # Extract date: e.g. "June 1, 2026" or might include hijri date
            # Take only the first part before any <p> tag
            date_cell = date_cell.split("<")[0].strip()
            parsed_date = parse_date_flexible(date_cell, default_year=datetime.now().year)
            if parsed_date is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_date",
                        message=f"row {row_num}: {date_cell!r}",
                        target_label="timetable",
                    )
                )
                continue

            for prayer, col_idx in jamaat_indices.items():
                if col_idx >= len(row):
                    continue
                raw_time = str(row[col_idx]).strip()
                if not raw_time:
                    continue

                jamaat = coerce_time(raw_time, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{parsed_date} {prayer.value}: {raw_time!r}",
                            target_label="timetable",
                        )
                    )
                    continue

                window = PLAUSIBLE_WINDOWS.get(prayer.value)
                if window and not (window[0] <= jamaat <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{parsed_date} {prayer.value}: {raw_time!r} outside window",
                            target_label="timetable",
                        )
                    )
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
                            raw_text=" | ".join(str(c) for c in row),
                            selector=f"table row {row_num}",
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
