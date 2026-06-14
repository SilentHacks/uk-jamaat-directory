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
    key = "hayes_welfare_association___abdulla_masjid_b93d5b8e"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("hayeswelfareassociation.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://hayeswelfareassociation.co.uk/timetable",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("fajr", "zuhr", "asr")
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
        # Date cells contain gregorian followed by hijri in a <p class="hijriDate">.
        # Strip from the first "<" onward so only the leading date remains for parsing.
        v = re.sub(r"\s*<.*$", "", v).strip()
        v = re.sub(r"<[^>]+>", "", v).strip()
        # Keep only the leading DD Month YYYY-ish token if extra text remains
        m = re.match(r"^(\d{1,2}\s+\w+\s+\d{4})", v)
        if m:
            v = m.group(1)
        return v

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        tables = html_helpers.extract_tables(artifact.text())
        for raw_table in tables:
            if len(raw_table.rows) < 3:
                continue
            # The second row (index 1) is the column labels header containing
            # "Date", "Day", "Begins", "Iqamah", ... (the first row is grouped names).
            col_header = [c.lower() for c in raw_table.rows[1]]
            if (
                "date" in col_header
                and "day" in col_header
                and any("iqamah" in c for c in col_header)
            ):
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
