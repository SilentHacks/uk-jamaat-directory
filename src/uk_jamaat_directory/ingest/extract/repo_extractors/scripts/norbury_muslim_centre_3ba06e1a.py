from __future__ import annotations

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
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
    PdfTableTimetableExtractor,
)


class Extractor(PdfTableTimetableExtractor):
    key = "norbury_muslim_centre_3ba06e1a"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("norburymuslimcentre.co.uk", "norburymuslimcentre.com"))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        from datetime import datetime

        now = datetime.now()
        month_str = now.strftime("%b-%Y")
        url = f"http://norburymuslimcentre.co.uk/s/06-{month_str}.pdf"
        self._targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets

    table_keywords = ("gregorian", "jamaat")
    date_column = "Gregorian Date"
    prayer_columns = {
        Prayer.FAJR: 4,
        Prayer.DHUHR: 7,
        Prayer.ASR: 9,
        Prayer.MAGHRIB: 11,
        Prayer.ISHA: 13,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        for page_tables in pdf_helpers.extract_tables(artifact.body):
            for raw_table in page_tables:
                if not raw_table:
                    continue
                cleaned = [[(cell or "") for cell in row] for row in raw_table if row]
                if not cleaned:
                    continue
                header_idx = None
                for i, r in enumerate(cleaned):
                    if any("gregorian" in (c or "").lower() for c in r) or any(
                        "jamaat" in (c or "").lower() for c in r
                    ):
                        if len([c for c in r if c]) > 3:
                            header_idx = i
                            break
                if header_idx is None:
                    continue
                effective_rows = cleaned[header_idx:]
                if len(effective_rows) < 2:
                    continue
                table = html_helpers.Table(effective_rows)
                if html_helpers.header_matches(table.header, list(self.table_keywords)):
                    return self._extract_from_table(ctx, table)
        return ExtractorResult(
            rows=[],
            warnings=[],
            no_schedule_reason="timetable table not found in PDF",
        )
