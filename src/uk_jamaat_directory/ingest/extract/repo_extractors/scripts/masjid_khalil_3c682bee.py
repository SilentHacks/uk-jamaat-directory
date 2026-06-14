from __future__ import annotations

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
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
    key = "masjid_khalil_3c682bee"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("masjidalkhalil.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # The /prayer-timetable/ page (and homepage) use the daily-prayer-time-for-mosques
        # WP plugin. A small "today" table is static, but the full monthly timetable is
        # injected client-side into #monthlyTimetable via AJAX. We target the public page
        # and rely on a JS-capable fetch (RENDERED_HTML) to obtain the rendered table HTML
        # for the current month (two header rows + data rows with explicit Iqamah/Jamaat).
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://masjidalkhalil.co.uk/prayer-timetable/",
                kind=TargetKind.RENDERED_HTML,
                requires_javascript=True,
            ),
        )

    table_keywords = ("date", "iqamah")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 8,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }

    def clean_cell(self, value: str) -> str:
        v = (value or "").strip()
        if "<" in v:
            v = html_helpers.strip_tags(v)
        v = " ".join(v.split())
        return v.strip()

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        # DPT monthly: thead row 0 = grouped prayer names (colspans), thead row 1 (or first tr)
        # is the sub-header with "Date", "Day", "Begins", "Iqamah", ... . Use that sub-header
        # as logical header, followed by data rows. Jamaat/Iqamah columns are the ones we map.
        for raw_table in html_helpers.extract_tables(html):
            rows = raw_table.rows
            if len(rows) < 2:
                continue
            # Look for the sub-header row that contains our keywords (Date + Iqamah)
            for i in range(min(3, len(rows) - 1)):
                if html_helpers.header_matches(rows[i], list(self.table_keywords)):
                    effective = html_helpers.Table([rows[i]] + rows[i + 1 :])
                    return self._extract_from_table(ctx, effective)
        # Fallback: let base report cleanly if no matching table structure.
        return ExtractorResult(
            rows=[],
            warnings=[
                ExtractorWarning(
                    code="no_table",
                    message="no dpt monthly timetable structure found",
                    target_label=self.target_label,
                )
            ],
            no_schedule_reason="timetable table not found",
        )
