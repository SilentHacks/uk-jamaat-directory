from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
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
    key = "abu_bakr_as_saddique_mosque_2d278ab8"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("mwht.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://mwht.org.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
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

        tables = extract_tables(artifact.text())
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

        # Find the table with "Jama'ah" in the header (contains both Begins and Jama'ah rows)
        target_table = None
        header_row_idx = None
        for table in tables:
            for row_idx in range(min(10, len(table.rows))):
                row_str = " ".join(table.rows[row_idx]).lower()
                if "jama" in row_str and "begins" in row_str:
                    target_table = table
                    header_row_idx = row_idx
                    break
            if target_table:
                break

        if not target_table:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="table_not_found",
                        message="timetable with 'Jama'ah' and 'Begins' not found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        # Extract data rows starting after the header
        data_rows = target_table.rows[header_row_idx + 1 :]

        extracted_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        year = datetime.now().year
        month = datetime.now().month

        for row_index, row in enumerate(data_rows, start=1):
            if len(row) < 11:
                continue

            # Column 0 is the date (day of month)
            date_str = row[0].strip()
            if not date_str or date_str in ("Jun", ""):
                continue

            try:
                day = int(date_str)
                row_date = date(year, month, day)
            except (ValueError, TypeError):
                warnings.append(
                    ExtractorWarning(
                        code="bad_date",
                        message=f"row {row_index} has invalid date '{date_str}'",
                        target_label="timetable",
                    )
                )
                continue

            # Prayer columns: FAJR=2, DHUHR=5, ASR=7, MAGHRIB=9, ISHA=10
            prayers_and_cols = [
                (Prayer.FAJR, 2),
                (Prayer.DHUHR, 5),
                (Prayer.ASR, 7),
                (Prayer.MAGHRIB, 9),
                (Prayer.ISHA, 10),
            ]

            for prayer, col_idx in prayers_and_cols:
                if col_idx >= len(row):
                    continue

                raw = row[col_idx].strip()
                if not raw or raw == "*****":
                    continue

                jamaat = coerce_time(raw, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue

                evidence = ctx.evidence(
                    target_label="timetable",
                    extractor_key=self.key,
                    extractor_version=self.version,
                    raw_text=" | ".join(row),
                    selector=f"table tbody tr:nth-child({row_index})",
                )

                extracted_rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
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
