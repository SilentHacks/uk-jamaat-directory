from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
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
    key = "aston_masjid_06630bec"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("astonmasjid.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.astonmasjid.com/s/timetable.pdf",
            kind=TargetKind.PDF,
            requires_pdf=True,
        ),
    )

    table_keywords = ("day", "fajr")
    date_column: str | int = 2
    prayer_columns: dict[Prayer, str | int] = {
        Prayer.FAJR: 4,
        Prayer.DHUHR: 7,
        Prayer.ASR: 9,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }
    use_carry_forward = False

    def clean_cell(self, value: str) -> str:
        v = (value or "").replace("\n", " ").strip()
        v = v.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
        return v

    def _extract_year_month_from_pdf(self, ctx: ExtractContext) -> tuple[int, int]:
        try:
            artifact = ctx.artifact(self.target_label)
            txt = pdf_helpers.extract_text(artifact.body) or ""
        except Exception:
            txt = ""
        year = datetime.now().year
        month = datetime.now().month
        m = re.search(r"\b(20\d{2})\b", txt)
        if m:
            year = int(m.group(1))
        m2 = re.search(
            r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
            r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\b",
            txt,
            re.IGNORECASE,
        )
        if m2:
            mon = parse_month_name(m2.group(1))
            if mon is not None:
                month = mon
        return year, month

    def current_year(self, ctx: ExtractContext) -> int:
        y, _ = self._extract_year_month_from_pdf(ctx)
        return y

    def current_month(self, ctx: ExtractContext) -> int:
        _, m = self._extract_year_month_from_pdf(ctx)
        return m
