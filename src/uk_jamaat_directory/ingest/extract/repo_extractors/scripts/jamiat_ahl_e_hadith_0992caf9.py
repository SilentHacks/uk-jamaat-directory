from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.html import Table
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
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
    key = "jamiat_ahl_e_hadith_0992caf9"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("web.archive.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://web.archive.org/web/20161124123516/http://www.greenlanemasjid.org/Prayer-Times.aspx",
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
            return __import__(
                "uk_jamaat_directory.ingest.extract.repo_extractors.contract",
                fromlist=["ExtractorResult"],
            ).ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        table = html_helpers.find_table(artifact.text(), header_keywords=list(self.table_keywords))
        if table is None:
            return __import__(
                "uk_jamaat_directory.ingest.extract.repo_extractors.contract",
                fromlist=["ExtractorResult", "ExtractorWarning"],
            ).ExtractorResult(
                rows=[],
                warnings=[
                    __import__(
                        "uk_jamaat_directory.ingest.extract.repo_extractors.contract",
                        fromlist=["ExtractorWarning"],
                    ).ExtractorWarning(
                        code="no_table",
                        message=f"no table matching {self.table_keywords}",
                        target_label=self.target_label,
                    )
                ],
                no_schedule_reason="timetable table not found",
            )
        # Site quirk: parsed header row has 12 cells (due to colspan in "Nov" label) while data rows have 13.
        # Align by prepending a blank cell to header so integer column indices work for jamaat columns.
        if table.rows and len(table.rows) > 1:
            data_len = max((len(r) for r in table.rows[1:]), default=0)
            if len(table.header) < data_len:
                pad = data_len - len(table.header)
                fixed_header = [""] * pad + list(table.header)
                fixed_rows = [fixed_header] + [list(r) for r in table.rows[1:]]
                table = Table(fixed_rows)
        return self._extract_from_table(ctx, table)
