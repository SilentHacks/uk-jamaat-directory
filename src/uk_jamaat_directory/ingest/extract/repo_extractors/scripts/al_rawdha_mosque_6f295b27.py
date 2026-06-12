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
    key = "al_rawdha_mosque_6f295b27"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("mkica.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.mkica.org/services-facilities/monthly-prayer-timetable/",
            kind=TargetKind.HTML,
        ),
    )

    # The monthly timetable (served statically) has two <thead> rows:
    #   row 0: "Day of Month", "Fajr" (colspan 2), "Sunrise", "Dhuhr"(2), ...
    #   row 1 (sub-header): "", "Begins", "Jama'a", "", "Begins", "Jama'a", ...
    # Data rows in <tbody>. We select on the sub-header (contains "Begins"/"Jama'a")
    # and use it as the effective header so jamaat columns can be indexed.
    table_keywords = ("begins", "jama'a")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 5,
        Prayer.ASR: 7,
        Prayer.MAGHRIB: 9,
        Prayer.ISHA: 11,
    }

    def clean_cell(self, value: str) -> str:
        v = (value or "").strip()
        if "<" in v:
            v = html_helpers.strip_tags(v)
        v = " ".join(v.split())
        return v.strip()

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        for raw_table in html_helpers.extract_tables(html):
            rows = raw_table.rows
            if len(rows) < 3:
                continue
            if html_helpers.header_matches(rows[1], list(self.table_keywords)):
                effective = html_helpers.Table([rows[1]] + rows[2:])
                return self._extract_from_table(ctx, effective)
        return ExtractorResult(
            rows=[],
            warnings=[
                ExtractorWarning(
                    code="no_table",
                    message="no shpt monthly timetable structure found",
                    target_label=self.target_label,
                )
            ],
            no_schedule_reason="timetable table not found",
        )
