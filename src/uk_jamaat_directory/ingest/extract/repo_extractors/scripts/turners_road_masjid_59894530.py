from __future__ import annotations

import re
from datetime import datetime

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
    key = "turners_road_masjid_59894530"
    version = "2026.06.18.1"
    source_match = SourceMatch(domains=("turnersroadmasjid.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://turnersroadmasjid.org/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("prayer", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "zuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
    }

    def clean_cell(self, value: str) -> str:
        v = (value or "").strip()
        if "jumu" in v.lower() or "jumma" in v.lower():
            return "jumuah"
        return v

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        all_tables = html_helpers.extract_tables(html)
        logical_header: list[str] | None = None
        body_rows: list[list[str]] = []
        date_text = ""
        for tbl in all_tables:
            for i, row in enumerate(tbl.rows):
                if html_helpers.header_matches(row, list(self.table_keywords)):
                    logical_header = [c for c in row]
                    if i > 0:
                        prev = tbl.rows[i - 1]
                        if len(prev) <= 2:
                            date_text = (prev[0] or "").strip()
                    body_rows = [list(r) for r in tbl.rows[i + 1 :]]
                    break
            if logical_header is not None:
                break
        if logical_header is None:
            # fallback: use the real header row we saw (row 1) when the declarative find fails
            for tbl in all_tables:
                if len(tbl.rows) >= 2 and html_helpers.header_matches(
                    tbl.rows[1], list(self.table_keywords)
                ):
                    logical_header = [c for c in tbl.rows[1]]
                    body_rows = [list(r) for r in tbl.rows[2:]]
                    break
            if logical_header is None:
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
        if not date_text:
            m = re.search(
                r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2}",
                html,
                re.IGNORECASE,
            )
            if m:
                date_text = m.group(0)
        if not date_text:
            date_text = datetime.now().strftime("%d %B %Y")
        jamaah_row: list[str] | None = None
        for r in body_rows:
            first = (r[0] or "").lower() if r else ""
            if "jam" in first:
                jamaah_row = list(r)
                break
        if jamaah_row is None and body_rows:
            jamaah_row = list(body_rows[-1])
        if not jamaah_row:
            return ExtractorResult(rows=[], no_schedule_reason="no jamaat row found")
        # Align the Jamā‘ah row to the 7-col header (Sunrise cell is missing due to rowspan)
        # Collected jamaah_row has 6 cells: [label, fajrJ, (sunriseSlot), jumuahJ, asrJ, maghribJ, ishaJ] but the sunrise slot is omitted in DOM.
        # Insert empty at index 2 to align: [label, fajrJ, '', jumuahJ, asrJ, maghribJ, ishaJ]
        if len(jamaah_row) == 6:
            jamaah_row = [
                jamaah_row[0],
                jamaah_row[1],
                "",
                jamaah_row[2],
                jamaah_row[3],
                jamaah_row[4],
                jamaah_row[5],
            ]
        if 0 <= self.date_column < len(jamaah_row):
            jamaah_row[self.date_column] = date_text
        # ensure header is cleaned consistently
        cleaned_header = [self.clean_cell(c) for c in (logical_header or [])]
        view = html_helpers.Table([cleaned_header, jamaah_row])
        return self._extract_from_table(ctx, view)
