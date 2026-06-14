from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
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
    key = "mosque___islamic_centre_3b43b2a3"
    version = "2026.06.13.12"
    source_match = SourceMatch(domains=("cradleyheathcentralmosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://cradleyheathcentralmosque.co.uk/namaztimetable.php",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("fajar", "zuhr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 5,
        Prayer.ASR: 7,
        Prayer.MAGHRIB: 9,
        Prayer.ISHA: 11,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """Override to find the nested table with prayer names."""
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        # Search for a row matching table_keywords, then use the next row as header
        for table in html_helpers.extract_tables(artifact.text()):
            for i, row in enumerate(table.rows):
                if html_helpers.header_matches(row, list(self.table_keywords)):
                    # Found the prayer names row (e.g., Fajar, Zuhr, etc.)
                    # The next row should be the headers (Date, Start, Jamat, etc.)
                    if i + 1 < len(table.rows):
                        remaining_rows = table.rows[i + 1 :]
                        logical_table = html_helpers.Table(remaining_rows)
                        return self._extract_from_table(ctx, logical_table)

        return ExtractorResult(
            rows=[],
            no_schedule_reason="timetable table not found",
        )
