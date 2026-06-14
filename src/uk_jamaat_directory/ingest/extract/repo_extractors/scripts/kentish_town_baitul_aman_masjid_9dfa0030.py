"""Kentish Town Baitul Aman Masjid prayer timetable extractor."""

from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import Table, extract_tables
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorResult,
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
    key = "kentish_town_baitul_aman_masjid_9dfa0030"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("ktbam.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://ktbam.co.uk/full-year-timetable",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("day", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 5,
        Prayer.ASR: 7,
        Prayer.MAGHRIB: 9,
        Prayer.ISHA: 11,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """Extract from monthly tables with multi-row headers."""
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html_content = artifact.text()
        tables = extract_tables(html_content)

        # Find monthly tables (header='January', 'February', etc.)
        months = (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        )

        for html_table in tables:
            if html_table.header and len(html_table.header) == 1:
                month_name = html_table.header[0].strip().lower()
                if month_name in months:
                    # This is a monthly table
                    rows_list = list(html_table.body())
                    if len(rows_list) >= 3:
                        # Synthesize full header from row 0 and row 1
                        header_0 = rows_list[
                            0
                        ]  # ['Day', 'Fajr', 'Sunrise', 'Zuhr', 'Asr', 'Magrib', 'Isha']
                        header_1 = rows_list[1]  # ['Begins', 'Jamah', 'Begins', 'Jamah', ...]

                        full_header = ["Day"]
                        # Each prayer has 2 sub-columns: Begins and Jamah (except Sunrise has none)
                        for i, prayer in enumerate(header_0[1:]):
                            if prayer.lower() == "sunrise":
                                full_header.append("Sunrise")
                            else:
                                # Get the corresponding Begins/Jamah pair from header_1
                                sub_idx = 2 * i
                                begins = header_1[sub_idx] if sub_idx < len(header_1) else "Begins"
                                jamah = (
                                    header_1[sub_idx + 1]
                                    if sub_idx + 1 < len(header_1)
                                    else "Jamah"
                                )
                                full_header.append(f"{prayer} {begins}")
                                full_header.append(f"{prayer} {jamah}")

                        # Now create the table with full header
                        table = Table(rows=[full_header] + rows_list[2:])
                        return self._extract_from_table(ctx, table)

        return ExtractorResult(
            rows=[],
            warnings=[
                ExtractorWarning(
                    code="no_table",
                    message="no monthly timetable found",
                    target_label=self.target_label,
                )
            ],
            no_schedule_reason="timetable table not found",
        )

    def accept_row(self, row: list[str], row_date: date) -> bool:
        """Accept rows with numeric day as first cell."""
        if not row or len(row) < 12:
            return False
        try:
            int(row[0].strip())
            return True
        except ValueError:
            return False
