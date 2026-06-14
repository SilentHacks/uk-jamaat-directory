"""Abubakr Siddiq Islamic Centre prayer timetable extractor."""

from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import Table
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
    key = "abubakr_siddiq_islamic_centre_670544a8"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("cambridgemosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://cma.cambridgemosque.com/onwebsite/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("prayer", "iqamah")
    date_column = "ignore"  # placeholder for daily display
    prayer_columns = {
        Prayer.FAJR: 2,  # IQAMAH column index
        Prayer.DHUHR: 2,
        Prayer.ASR: 2,
        Prayer.MAGHRIB: 2,
        Prayer.ISHA: 2,
    }

    def _extract_from_table(self, ctx: ExtractContext, table: Table) -> ExtractorResult:
        """Extract from daily prayer times table without a date column."""
        header = [self.clean_cell(cell) for cell in table.header]

        # Use today's date for all rows in a daily display
        row_date = date.today()
        body = [[self.clean_cell(cell) for cell in row] for row in table.body()]
        rows: list[ExtractorRow] = []

        for row_number, row in enumerate(body, start=1):
            # Extract prayer name from first column
            if not row:
                continue
            prayer_name = row[0].lower()

            # Map prayer name to Prayer enum
            prayer_map = {
                "fajr": Prayer.FAJR,
                "zuhr": Prayer.DHUHR,
                "asr": Prayer.ASR,
                "maghrib": Prayer.MAGHRIB,
                "isha": Prayer.ISHA,
                "jumuah": Prayer.DHUHR,  # Jumuah often maps to Dhuhr slot
            }

            prayer = prayer_map.get(prayer_name)
            if not prayer:
                continue

            # Extract jamaat time from IQAMAH column (index 2)
            if len(row) <= 2:
                continue
            raw = row[2]
            if not raw:
                continue

            jamaat = coerce_time(raw, prayer=prayer.value)
            if jamaat is None:
                continue

            rows.append(
                ExtractorRow(
                    date=row_date,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    start_time=None,
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
                warnings=[],
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=rows, warnings=[])
