from __future__ import annotations

import re

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.html import Table
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
    key = "oldham_central_masjid_and_islamic_centre_593067f5"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("ocmic.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    table_keywords = ("date", "day")
    date_column: str | int = 0
    prayer_columns: dict[Prayer, str | int] = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 8,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }

    def __init__(self) -> None:
        super().__init__()
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://ocmic.org.uk/monthly",
                kind=TargetKind.RENDERED_HTML,
                requires_javascript=True,
            ),
        )

    def clean_cell(self, value: str) -> str:
        v = (value or "").strip()
        if "<" in v:
            v = html_helpers.strip_tags(v)
        v = " ".join(v.split())
        return v

    def _extract_rows_from_html(self, html: str) -> list[list[str]]:
        rows: list[list[str]] = []
        for tr in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S):
            cells: list[str] = []
            for m in re.finditer(r"<t[dh][^>]*>(.*?)</t[dh]>", tr.group(1), re.I | re.S):
                txt = re.sub(r"<[^>]+>", " ", m.group(1))
                txt = " ".join(txt.split())
                cells.append(txt)
            if any(cells):
                rows.append(cells)
        return rows

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        rows = self._extract_rows_from_html(html)
        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable table not found",
            )
        header_idx: int | None = None
        for i, r in enumerate(rows):
            low = " ".join((c or "").lower() for c in r)
            if "date" in low and "day" in low:
                header_idx = i
                break
        if header_idx is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable table not found",
            )
        header = rows[header_idx]
        body = rows[header_idx + 1 :]
        table = Table([header] + body)
        return self._extract_from_table(ctx, table)
