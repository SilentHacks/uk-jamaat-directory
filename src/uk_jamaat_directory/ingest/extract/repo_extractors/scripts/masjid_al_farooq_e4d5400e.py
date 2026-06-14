from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.html import Table
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
    key = "masjid_al_farooq_e4d5400e"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("web.archive.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://web.archive.org/web/20161216080151/http://www.greenlanemasjid.org/Prayer-Times.aspx",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("fajr", "jamat")
    date_column = 1
    prayer_columns = {
        Prayer.FAJR: 4,
        Prayer.DHUHR: 7,
        Prayer.ASR: 9,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        table = html_helpers.find_table(artifact.text(), header_keywords=list(self.table_keywords))
        if table is None:
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
        # Site quirk: header has 12 cells (colspan) but data rows have 13.
        # Prepend blank cell to header so int indices work for jamaat cols.
        if table.rows and len(table.rows) > 1:
            data_len = max((len(r) for r in table.rows[1:]), default=0)
            if len(table.header) < data_len:
                pad = data_len - len(table.header)
                fixed_header = [""] * pad + list(table.header)
                fixed_rows = [fixed_header] + [list(r) for r in table.rows[1:]]
                table = Table(fixed_rows)
        return self._extract_from_table(ctx, table)
