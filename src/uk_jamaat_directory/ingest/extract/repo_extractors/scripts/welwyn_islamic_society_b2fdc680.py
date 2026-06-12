from __future__ import annotations

import re

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
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
    key = "welwyn_islamic_society_b2fdc680"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("welwynis.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://www.welwynis.org/daily-prayer-time/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("date", "fajr")
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
        # Strip any inline markup or trailing junk after the first tag (hijri etc.)
        v = re.sub(r"\s*<.*$", "", v).strip()
        v = re.sub(r"<[^>]+>", "", v).strip()
        return v

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        for raw_table in tables:
            if len(raw_table.rows) < 3:
                continue
            # Second row (index 1) is the column labels: Date, Day, Begins, Iqamah, ...
            # The first row is grouped prayer names (Fajr, Duhr, ...).
            col_header = [c.lower() for c in raw_table.rows[1]]
            if "date" in col_header and any("iqamah" in c for c in col_header):
                synthetic_rows = [raw_table.rows[1]] + raw_table.rows[2:]
                synthetic = html_helpers.Table(synthetic_rows)
                return self._extract_from_table(ctx, synthetic)
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
