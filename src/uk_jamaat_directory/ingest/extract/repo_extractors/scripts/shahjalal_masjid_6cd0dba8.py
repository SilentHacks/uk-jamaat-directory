from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_month_name
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    PdfTableTimetableExtractor,
)


class Extractor(PdfTableTimetableExtractor):
    key = "shahjalal_masjid_6cd0dba8"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("shahjalalmosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    targets = (
        TargetSpec(
            label="timetable",
            url="https://shahjalalmosque.co.uk/Calendar/Shahjalal%20%D9%90Apr%2026.pdf",
            kind=TargetKind.PDF,
            requires_pdf=True,
        ),
    )

    table_keywords = ("date", "fajr")
    date_column: str | int = 0
    prayer_columns: dict[Prayer, str | int] = {
        Prayer.FAJR: 4,
        Prayer.DHUHR: 9,
        Prayer.ASR: 15,
        Prayer.MAGHRIB: 19,
        Prayer.ISHA: 23,
    }
    use_carry_forward = False

    def clean_cell(self, value: str) -> str:
        v = (value or "").replace("\n", " ").strip()
        v = v.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
        return v

    def _parse_year_month_from_target(self, ctx: ExtractContext) -> tuple[int, int]:
        url = ""
        try:
            url = ctx.artifact(self.target_label).target_url or ""
        except Exception:
            pass
        if not url:
            for t in self.targets:
                if t.label == self.target_label:
                    url = t.url
                    break
        year = datetime.now().year
        month = datetime.now().month
        m = re.search(r"(20\d{2})", url)
        if m:
            year = int(m.group(1))
        m2 = re.search(
            r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
            r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\b",
            url,
            re.IGNORECASE,
        )
        if m2:
            mon = parse_month_name(m2.group(1))
            if mon is not None:
                month = mon
        return year, month

    def current_year(self, ctx: ExtractContext) -> int:
        y, _ = self._parse_year_month_from_target(ctx)
        return y

    def current_month(self, ctx: ExtractContext) -> int:
        _, m = self._parse_year_month_from_target(ctx)
        return m
