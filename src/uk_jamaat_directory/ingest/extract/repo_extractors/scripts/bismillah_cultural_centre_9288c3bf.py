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
    key = "bismillah_cultural_centre_9288c3bf"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("bismillahcentre.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://bismillahcentre.com/?section=prayer",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "jamat")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 4,
        Prayer.DHUHR: 7,
        Prayer.ASR: 9,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }

    def clean_cell(self, value: str) -> str:
        v = (value or "").strip()
        if "<" in v:
            v = re.sub(r"<[^>]+>", "", v)
        v = " ".join(v.split())
        return v.strip()

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        for raw_table in tables:
            label_idx = None
            for i, row in enumerate(raw_table.rows):
                low = [c.lower() for c in row]
                if "date" in low and "day" in low:
                    label_idx = i
                    break
            if label_idx is None:
                continue
            header = [self.clean_cell(c) for c in raw_table.rows[label_idx]]
            body_rows = [[self.clean_cell(c) for c in r] for r in raw_table.rows[label_idx + 1 :]]
            if not body_rows:
                continue
            synthetic = html_helpers.Table([header] + body_rows)
            return self._extract_from_table(ctx, synthetic)
        return ExtractorResult(
            rows=[],
            warnings=[
                ExtractorWarning(
                    code="no_table",
                    message="no table with date/day label row found",
                    target_label=self.target_label,
                )
            ],
            no_schedule_reason="timetable table not found",
        )
