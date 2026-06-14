import re

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
    key = "central_mosque_wembley_285b0670"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("wembleycentralmasjid.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://wembleycentralmasjid.co.uk/prayer-times",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 9,
        Prayer.MAGHRIB: 11,
        Prayer.ISHA: 13,
    }

    def clean_cell(self, value: str) -> str:
        v = (value or "").strip()
        if "&" in v:
            m = re.search(r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?\.?)", v, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return v

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        prayer_table = None
        for t in tables:
            joined = " ".join(" ".join(r) for r in t.rows).lower()
            if "date" in joined and "iqamah" in joined and len(t.rows) > 5:
                prayer_table = t
                break
        if prayer_table is None:
            for t in tables:
                joined = " ".join(" ".join(rr) for rr in t.rows).lower()
                if "date" in joined and len(t.rows) > 10:
                    prayer_table = t
                    break
        if prayer_table is None:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")
        hdr_idx = 0
        for i, row in enumerate(prayer_table.rows):
            if any("date" in c.lower() for c in row):
                hdr_idx = i
                break
        logical_header = [self.clean_cell(c) for c in prayer_table.rows[hdr_idx]]
        data_rows = [[self.clean_cell(c) for c in r] for r in prayer_table.rows[hdr_idx + 1 :]]
        effective = html_helpers.Table([logical_header] + data_rows)
        return self._extract_from_table(ctx, effective)
