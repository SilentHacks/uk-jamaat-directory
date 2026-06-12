from __future__ import annotations

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
    key = "eritrean_muslim_community_association_7cb87fef"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("emca.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://emca.org.uk/prayer-time/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr jamaat",
        Prayer.DHUHR: "dhuhr jamaat",
        Prayer.ASR: "asr jamaat",
        Prayer.MAGHRIB: "maghrib jamaat",
        Prayer.ISHA: "isha jamaat",
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no table found on page",
                        target_label=self.target_label,
                    )
                ],
                no_schedule_reason="timetable table not found",
            )
        raw = tables[0]
        rows = raw.rows
        if len(rows) < 3:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="table too small to contain data",
                        target_label=self.target_label,
                    )
                ],
                no_schedule_reason="timetable table not found",
            )
        # Row 0: nav
        # Row 1: prayer group labels (Fajr, Sunrise, Dhuhr, ...)
        # Row 2: Entry / Jamaà sub-headers (10 cells)
        # Row 3+: data rows (12 cells: day + 2 per prayer + sunrise value)
        data_rows = rows[3:]
        if not data_rows:
            return ExtractorResult(
                rows=[],
                warnings=[
                    html_helpers.ExtractorWarning(
                        code="no_table",
                        message="table contained no data rows",
                        target_label=self.target_label,
                    )
                ],
                no_schedule_reason="no extractable rows",
            )
        # Synthesize a 12-column header aligned with the data row layout.
        # This lets the base class use keyword or index lookup on a single header row.
        header = [
            "date",
            "fajr entry",
            "fajr jamaat",
            "sunrise",
            "dhuhr entry",
            "dhuhr jamaat",
            "asr entry",
            "asr jamaat",
            "maghrib entry",
            "maghrib jamaat",
            "isha entry",
            "isha jamaat",
        ]
        effective = html_helpers.Table([header] + data_rows)
        return self._extract_from_table(ctx, effective)
