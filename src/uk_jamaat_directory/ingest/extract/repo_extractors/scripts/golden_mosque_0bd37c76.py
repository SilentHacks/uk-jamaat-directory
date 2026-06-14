from datetime import datetime
import re

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.html import Table
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
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
    key = "golden_mosque_0bd37c76"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("goldenmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://goldenmosque.org/prayer-times/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("fajr", "zuhr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 9,
        Prayer.MAGHRIB: 11,
        Prayer.ISHA: 13,
    }

    def clean_cell(self, value: str) -> str:
        v = value.strip()
        # The Date column cells contain the gregorian date followed by hijri in a <p>.
        # After text extraction this becomes e.g. "June 1, 2026 15 Dhū al-Hijjah 1447".
        # Keep only the leading "Month Day, Year" for reliable date parsing.
        if re.search(r"\d{4}", v) and re.search(
            r"(Dhū|Muharram|Hijjah|Ṣafar|Rabī|Jumād|Rajab|Shaʿbān|Ramadān|Shawwāl|Qaʿdah)",
            v,
            re.IGNORECASE,
        ):
            m = re.match(r"^([A-Za-z]+ \d+, \d{4})", v)
            if m:
                return m.group(1)
        return v

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        table = html_helpers.find_table(html, header_keywords=list(self.table_keywords))
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
        # The <table> has two header rows: grouped prayer names (row 0), then
        # the actual column labels including "Date", "Iqamah" etc (row 1).
        # Data rows follow. Rebuild a Table using the sub-header as the header
        # so column index lookups in the base class find "Date"/"Iqamah".
        if len(table.rows) < 3:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table has no data rows")
        subheader = table.rows[1]
        data_rows = table.rows[2:]
        fixed_rows = [list(subheader)] + [list(r) for r in data_rows]
        norm_table = Table(fixed_rows)
        return self._extract_from_table(ctx, norm_table)
