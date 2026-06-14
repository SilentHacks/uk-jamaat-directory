from __future__ import annotations

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
    key = "masjid_e_noor_fcb8a001"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("masjidenoor.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidenoor.org.uk/prayer-times.php",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "zohar",
        Prayer.ASR: "asar",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        # The page has a two-row header: first row is "BEGINNING TIMES / JAMAAT TIMES" (colspans),
        # second row is the actual column names. html_helpers.Table treats the first <tr> as .header.
        # Locate the table that contains the keywords in its *second* row, then build an effective
        # Table so that the column-name row becomes .header for the base _extract_from_table logic.
        for raw_table in html_helpers.extract_tables(html):
            rows = raw_table.rows
            if len(rows) < 2:
                continue
            # Check if the column header row (index 1) contains our keywords
            if html_helpers.header_matches(rows[1], list(self.table_keywords)):
                # Re-wrap so rows[1] is treated as the header
                effective = html_helpers.Table([rows[1]] + rows[2:])
                return self._extract_from_table(ctx, effective)
        # Fallback to default (will produce the documented "no table" reason)
        return super().extract(ctx)
