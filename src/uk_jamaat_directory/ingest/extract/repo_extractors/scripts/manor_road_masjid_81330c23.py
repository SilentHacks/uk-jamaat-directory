from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.html import Table
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
    key = "manor_road_masjid_81330c23"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("bismillahcentre.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://bismillahcentre.com/?section=prayer",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "begins")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr jamat",
        Prayer.DHUHR: "dhuhr jamat",
        Prayer.ASR: "asr jamat",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "ishaa jamat",
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        # Extract all tables and find the one with the timetable data
        tables = html_helpers.extract_tables(artifact.text())
        for table in tables:
            # This table has prayer names in row 0, column headers in row 1
            if len(table.rows) > 1 and "date" in [c.lower() for c in table.rows[1]]:
                header_row = table.rows[1]

                # Synthesize header by prepending prayer names to relevant columns
                # Structure: Date, Day, Islamic, [Fajr: Begins, Jamat], Sunrise,
                #           [Dhuhr: Begins, Jamat], [Asr: Begins, Jamat],
                #           [Maghrib: Begins], [Ishaa: Begins, Jamat]
                prayers_with_cols = [
                    ("fajr", 3, 2),  # prayer, start col, span
                    ("dhuhr", 6, 2),
                    ("asr", 8, 2),
                    ("maghrib", 10, 1),
                    ("ishaa", 11, 2),
                ]

                enhanced_header = list(header_row)
                for prayer, start_col, span in prayers_with_cols:
                    for offset in range(span):
                        col_idx = start_col + offset
                        if col_idx < len(enhanced_header):
                            # Only add prayer prefix if it's not already there
                            if not any(
                                p in enhanced_header[col_idx].lower()
                                for p, _, _ in prayers_with_cols
                            ):
                                enhanced_header[col_idx] = f"{prayer} {enhanced_header[col_idx]}"

                # Create a new table with enhanced header
                fixed_table = Table([enhanced_header] + table.rows[2:])
                return self._extract_from_table(ctx, fixed_table)

        return ExtractorResult(
            rows=[],
            warnings=[
                ExtractorWarning(
                    code="no_table",
                    message=f"no table matching {self.table_keywords}",
                    target_label=self.target_label,
                )
            ],
            no_schedule_reason="timetable table not found",
        )

    def clean_cell(self, value: str) -> str:
        """Handle Friday asterisk and empty cells."""
        if value == "*":
            return ""
        return value
