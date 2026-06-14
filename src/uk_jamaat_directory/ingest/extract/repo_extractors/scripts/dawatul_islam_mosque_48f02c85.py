from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.html import Table
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorResult,
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
    key = "dawatul_islam_mosque_48f02c85"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("dawatulig.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://dawatulig.org.uk/Timetable.aspx",
            kind=TargetKind.HTML,
        ),
    )

    table_keywords = ("fajr",)
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 4,
        Prayer.DHUHR: 7,
        Prayer.ASR: 10,
        Prayer.MAGHRIB: 12,
        Prayer.ISHA: 14,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """Extract from the big monthly table."""
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        text = artifact.text()
        all_tables = html_helpers.extract_tables(text)

        # Find the big table and use row 3 as header, row 4+ as data
        for raw_table in all_tables:
            if len(raw_table.rows) > 50 and len(raw_table.rows[3]) >= 15:
                # This is the big table; find the first month section only
                body_rows = raw_table.rows[4:]

                # Extract only the first month by detecting when day wraps (e.g., 30 -> 1)
                month_rows = []
                prev_day = 0
                for row in body_rows:
                    if not row or not row[0]:
                        break
                    try:
                        day = int(str(row[0]).strip())
                        # Wrap detected: new month section, stop extraction
                        if day < prev_day:
                            break
                        month_rows.append(row)
                        prev_day = day
                    except ValueError:
                        # Non-numeric day, end of month section
                        break

                reconstructed_rows = [raw_table.rows[3]] + month_rows
                reconstructed = Table(rows=reconstructed_rows)
                return self._extract_from_table(ctx, reconstructed)

        return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")

    def accept_row(self, row, row_date) -> bool:
        """Accept rows that are data rows."""
        if not row or not row[0]:
            return False
        try:
            int(str(row[0]).strip())
        except ValueError:
            return False
        return True
