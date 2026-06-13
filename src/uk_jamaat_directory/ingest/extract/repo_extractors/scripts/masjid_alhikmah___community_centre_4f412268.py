import re
from datetime import date
from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.helpers.relative import jamaat_after_start
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    ExtractorWarning,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    TableTimetableExtractor,
)
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers


class Extractor(TableTimetableExtractor):
    key = "masjid_alhikmah___community_centre_4f412268"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("masjidalhikmah.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidalhikmah.org.uk/prayer-times/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = 0
    start_columns = {
        Prayer.MAGHRIB: 8,
    }
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 5,
        Prayer.ASR: 7,
        Prayer.MAGHRIB: 9,
        Prayer.ISHA: 11,
    }

    def clean_cell(self, value):
        """Skip unparseable times like '+5 mins'."""
        value = value.strip()
        if value.startswith("+"):
            return ""
        return value

    def accept_row(self, row, row_date: date) -> bool:
        """Accept all rows with valid dates."""
        return True

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """Override to handle '+5 mins' relative times for Maghrib."""
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        
        table = html_helpers.find_table(artifact.text(), header_keywords=list(self.table_keywords))
        if table is None:
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
        
        # Call parent's extraction but intercept rows to handle Maghrib "+5 mins"
        base_result = self._extract_from_table(ctx, table)
        
        # Post-process to handle "+5 mins" for Maghrib jamaat
        processed_rows = []
        for row in base_result.rows:
            if row.prayer == Prayer.MAGHRIB and row.jamaat_time is None and row.start_time is not None:
                # Re-check the raw text for "+5 mins"
                raw_text = row.evidence.raw_text if row.evidence else ""
                cells = raw_text.split(" | ")
                if len(cells) > 9 and cells[9].strip().startswith("+"):
                    match = re.match(r"\+(\d+)\s*mins?", cells[9].strip())
                    if match:
                        offset_mins = int(match.group(1))
                        jamaat = jamaat_after_start(row.start_time, offset_mins)
                        if jamaat is not None:
                            row.jamaat_time = jamaat
                            processed_rows.append(row)
                            continue
            processed_rows.append(row)
        
        return ExtractorResult(rows=processed_rows, warnings=base_result.warnings)
