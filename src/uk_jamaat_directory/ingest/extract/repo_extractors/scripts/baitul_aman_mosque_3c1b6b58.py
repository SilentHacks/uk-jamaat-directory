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
    key = "baitul_aman_mosque_3c1b6b58"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("baitulaman.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://baitulaman.org/prayer-times",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("fajr", "zuhr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 5,
        Prayer.ASR: 7,
        Prayer.MAGHRIB: 9,
        Prayer.ISHA: 11,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        self._last_day = None
        self._stopped = False
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        # Find table and merge first two rows as header
        tables = html_helpers.extract_tables(artifact.text())
        table = None
        for t in tables:
            if len(t.rows) > 1:
                # Merge rows 0 and 1 to create composite header
                header_0 = t.rows[0]
                header_1 = t.rows[1]
                merged_header = []
                for i in range(max(len(header_0), len(header_1))):
                    h0 = header_0[i].lower() if i < len(header_0) else ""
                    h1 = header_1[i].lower() if i < len(header_1) else ""
                    merged = f"{h0} {h1}".strip()
                    merged_header.append(merged)

                # Check if keywords match
                if all(kw.lower() in " ".join(merged_header) for kw in self.table_keywords):
                    # Create new table with merged header and original body (skip first 2 rows)
                    table = Table([merged_header] + t.rows[2:])
                    break

        if table is None:
            return ExtractorResult(
                rows=[],
                warnings=[],
                no_schedule_reason="timetable table not found",
            )
        return self._extract_from_table(ctx, table)

    def accept_row(self, row, row_date):
        """Accept only rows within the first month; stop when we see a date reset."""
        if self._stopped:
            return False
        if not row or not row[0].strip():
            return False
        try:
            day = int(row[0].strip())
            if not (1 <= day <= 31):
                return False
            # After seeing high days (28+), if we encounter a low day (1-7), we've switched months
            if self._last_day is not None:
                if self._last_day >= 28 and day <= 7:
                    self._stopped = True
                    return False
                if day < self._last_day:
                    # Day decreased; likely a new month section
                    self._stopped = True
                    return False
            self._last_day = day
            return True
        except (ValueError, IndexError):
            return False
