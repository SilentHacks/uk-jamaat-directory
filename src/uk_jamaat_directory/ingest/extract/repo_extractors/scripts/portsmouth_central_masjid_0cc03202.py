from __future__ import annotations

import re

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
    key = "portsmouth_central_masjid_0cc03202"
    version = "2026.06.18.1"
    source_match = SourceMatch(domains=("portsmouthcentralmasjid.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://www.portsmouthcentralmasjid.com/Prayer-Times",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr jama",
        Prayer.DHUHR: "zuhr jama",
        Prayer.JUMUAH: "jumu",
        Prayer.ASR: "asr jama",
        Prayer.MAGHRIB: "maghrib jama",
        Prayer.ISHA: "isha jama",
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()

        # Prefer the explicitly id'd table; fall back to keyword header search.
        table_html: str | None = None
        m = re.search(
            r'<table[^>]*id=["\']tbl_PrayerTimes["\'][^>]*>(.*?)</table>',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            table_html = m.group(1)
        if table_html is None:
            tbl = html_helpers.find_table(html, header_keywords=list(self.table_keywords))
            if tbl is not None:
                # Reconstruct a minimal table html from the parsed rows for rel extraction below.
                # (find_table succeeded but we still need rel attrs; fall through to raw scan.)
                pass

        # Collect header cells and data rows with their rel=DDMMYYYY.
        header_cells: list[str] = []
        body_rows: list[list[str]] = []

        if table_html:
            # Extract header row (first tr with th or td)
            header_m = re.search(
                r"<tr[^>]*>(.*?)</tr>",
                table_html,
                re.IGNORECASE | re.DOTALL,
            )
            if header_m:
                header_cells = self._extract_td_texts(header_m.group(1))
            # Extract data rows that carry rel="DDMMYYYY"
            for dm in re.finditer(
                r"<tr[^>]*?rel=['\"](\d{2})(\d{2})(\d{4})['\"][^>]*>(.*?)</tr>",
                table_html,
                re.IGNORECASE | re.DOTALL,
            ):
                dd, mm, yyyy, inner = dm.groups()
                cells = self._extract_td_texts(inner)
                if not cells:
                    continue
                # Replace the first cell (bare day number) with a full date string
                # so the base parser gets an unambiguous date regardless of month blocks.
                date_str = f"{int(dd)}/{int(mm)}/{yyyy}"
                if cells:
                    cells[0] = date_str
                body_rows.append(cells)
        else:
            # Fallback: use the declarative table finder and parse all rows as-is
            # (will rely on current month for bare day numbers; still better than nothing).
            tbl = html_helpers.find_table(html, header_keywords=list(self.table_keywords))
            if tbl is None:
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
            header_cells = [self.clean_cell(c) for c in tbl.header]
            for r in tbl.body():
                body_rows.append([self.clean_cell(c) for c in r])

        if not header_cells:
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

        # Build a synthetic Table with corrected date column values in body.
        cleaned_header = [self.clean_cell(c) for c in header_cells]
        cleaned_body = [[self.clean_cell(c) for c in row] for row in body_rows]
        view = html_helpers.Table([cleaned_header] + cleaned_body)
        return self._extract_from_table(ctx, view)

    @staticmethod
    def _extract_td_texts(inner_html: str) -> list[str]:
        texts: list[str] = []
        for tm in re.finditer(r"<t[dh][^>]*>(.*?)</t[dh]>", inner_html, re.IGNORECASE | re.DOTALL):
            raw = tm.group(1)
            # Strip any nested tags
            txt = re.sub(r"<[^>]+>", " ", raw)
            txt = re.sub(r"\s+", " ", txt).strip()
            texts.append(txt)
        return texts
