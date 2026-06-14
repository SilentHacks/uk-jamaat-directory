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
    key = "salafi_masjid_7b468003"
    version = "2026.06.12.4"
    source_match = SourceMatch(domains=("wrightstreetmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.wrightstreetmosque.com/wp-content/uploads/2026/05/June-2026-TT.pdf",
            kind=TargetKind.PDF,
            requires_pdf=True,
        ),
    )

    table_keywords = ("day", "fajr")
    date_column: str | int = 6
    prayer_columns: dict[Prayer, str | int] = {
        Prayer.FAJR: 12,
        Prayer.DHUHR: 21,
        Prayer.ASR: 27,
        Prayer.MAGHRIB: 30,
        Prayer.ISHA: 36,
    }
    use_carry_forward = False

    def clean_cell(self, value: str) -> str:
        v = (value or "").replace("\n", " ").strip()
        v = v.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
        v = v.replace("ā", "a").replace("Ā", "A")
        return v

    def _extract_year_month_from_pdf(self, ctx: ExtractContext) -> tuple[int, int]:
        try:
            artifact = ctx.artifact(self.target_label)
            doc = pdf_helpers.open_pdf(artifact.body)
            page = doc[0]
            txt = page.get_text() or ""
            doc.close()
        except Exception:
            txt = ""
        year = datetime.now().year
        month = datetime.now().month
        m = re.search(r"\b(20\d{2})\b", txt)
        if m:
            year = int(m.group(1))
        m2 = re.search(
            r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\b",
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
