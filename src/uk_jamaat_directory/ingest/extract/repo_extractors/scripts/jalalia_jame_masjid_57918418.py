from __future__ import annotations

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
    key = "jalalia_jame_masjid_57918418"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("jalaliajaamemosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://jalaliajaamemosque.org.uk/monthly-timetable",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")

    # Indices into the effective header we synthesize (Date, Day, Begins, Jama'ah, ...)
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 8,
        Prayer.MAGHRIB: 9,
        Prayer.ISHA: 11,
    }

    def clean_cell(self, value: str) -> str:
        v = (value or "").strip()
        # Remove any embedded markup
        if "<" in v:
            v = re.sub(r"<[^>]+>", "", v)
        v = " ".join(v.split())
        return v.strip()

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        for raw_table in html_helpers.extract_tables(html):
            rows = raw_table.rows
            if len(rows) < 3:
                continue
            # rows[0] is grouped header (Fajr, Zuhr, ...)
            # rows[1] is sub-header with Begins/Jama'ah labels (10 cells)
            sub = [c.lower() for c in rows[1]]
            if not any("jama" in c for c in sub):
                continue
            # data rows start at rows[2:], each with 12 cells: Date, Day, + 10 sub values
            data_rows = rows[2:]
            if not data_rows:
                continue
            # Build synthetic header row of 12 cells so indices align with data
            # positions: 0=Date, 1=Day, 2=Fajr Begins, 3=Fajr Jama'ah, 4=Sunrise, ...
            synth_header = ["Date", "Day"] + rows[1]
            # pad/truncate to match first data row width if needed
            first_data_len = len(data_rows[0]) if data_rows else len(synth_header)
            if len(synth_header) < first_data_len:
                synth_header = synth_header + [""] * (first_data_len - len(synth_header))
            elif len(synth_header) > first_data_len:
                synth_header = synth_header[:first_data_len]
            effective = Table([synth_header] + data_rows)
            # Now delegate to the base table logic with our effective header
            return self._extract_from_table(ctx, effective)
        return ExtractorResult(
            rows=[],
            warnings=[
                ExtractorWarning(
                    code="no_table",
                    message="no monthly timetable structure found",
                    target_label=self.target_label,
                )
            ],
            no_schedule_reason="timetable table not found",
        )
