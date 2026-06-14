from __future__ import annotations

from datetime import datetime

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
    key = "stanford_le_hope_jamme_masjid_5a7dd452"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("stanfordlehopemosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://stanfordlehopemosque.org/full-year-timetable",
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

    def current_year(self, ctx: ExtractContext) -> int:
        return datetime.now().year

    def current_month(self, ctx: ExtractContext) -> int:
        return datetime.now().month

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        all_tables = html_helpers.extract_tables(html)
        if not all_tables:
            return ExtractorResult(rows=[], no_schedule_reason="no tables found")

        now = datetime.now()
        month_name = now.strftime("%B")
        month_table = None
        for tbl in all_tables:
            if tbl.rows and (tbl.rows[0][0] or "").strip().lower() == month_name.lower():
                month_table = tbl
                break
        if month_table is None:
            for tbl in all_tables:
                if len(tbl.rows) >= 5:
                    month_table = tbl
                    break
        if month_table is None:
            month_table = all_tables[0]

        if len(month_table.rows) <= 3:
            return ExtractorResult(rows=[], no_schedule_reason="no data rows in month table")

        data_rows: list[list[str]] = []
        for r in month_table.rows[3:]:
            if r and (r[0] or "").strip().lstrip("0").isdigit():
                data_rows.append(list(r))

        if not data_rows:
            return ExtractorResult(rows=[], no_schedule_reason="no data rows found")

        synthetic_header = [f"c{k}" for k in range(12)]
        view = html_helpers.Table([synthetic_header] + data_rows)
        return self._extract_from_table(ctx, view)
