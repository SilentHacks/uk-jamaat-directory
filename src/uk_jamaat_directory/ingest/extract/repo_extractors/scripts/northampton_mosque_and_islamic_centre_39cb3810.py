from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
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
    key = "northampton_mosque_and_islamic_centre_39cb3810"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("northamptonislamiccentre.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://northamptonislamiccentre.com/timetable/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("date", "iqamah")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 9,
        Prayer.MAGHRIB: 11,
        Prayer.ISHA: 13,
    }

    def clean_cell(self, value: str) -> str:
        return (value or "").strip()

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        dpt_table = None
        for t in tables:
            for i, row in enumerate(t.rows):
                row_lower = [(c or "").lower() for c in row]
                if "date" in row_lower:
                    header_row = [self.clean_cell(c) for c in row]
                    data_rows = [[self.clean_cell(c) for c in r] for r in t.rows[i + 1 :]]
                    if data_rows and any(any(cell for cell in r) for r in data_rows):
                        logical = html_helpers.Table([header_row] + data_rows)
                        dpt_table = logical
                        break
            if dpt_table is not None:
                break
        if dpt_table is None:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")
        return self._extract_from_table(ctx, dpt_table)
