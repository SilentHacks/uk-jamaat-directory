from __future__ import annotations

import re
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
    key = "bait_ul_aziz_islamic_cultural_centre_96959238"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("baitulazizmosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://baitulazizmosque.org.uk/prayer-times",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("date", "jam")
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
        # Strip embedded hijri <p class="hijriDate">...</p> (and any tags) from date cells
        if "<p" in v.lower() or "dhū" in v.lower() or "hijri" in v.lower():
            if "<" in v:
                v = v.split("<", 1)[0]
            else:
                v = " ".join(v.split()[:3])
        # Also strip any remaining inline markup
        v = re.sub(r"<[^>]+>", "", v).strip()
        return v

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        # The page renders a monthly dptTimetable via JS.
        # It has two header rows: grouped prayer names, then sub-headers
        # (Date, Day, Begins, Jamā‘ah, Sunrise, Begins, Jamā‘ah, ...).
        # Use the sub-header row as the effective header for column mapping.
        for raw_table in html_helpers.extract_tables(html):
            rows = raw_table.rows
            if len(rows) < 2:
                continue
            if html_helpers.header_matches(rows[1], list(self.table_keywords)):
                effective = html_helpers.Table([rows[1]] + rows[2:])
                return self._extract_from_table(ctx, effective)
        # Fallback lets the base report a clean "no table" if needed.
        return super().extract(ctx)
