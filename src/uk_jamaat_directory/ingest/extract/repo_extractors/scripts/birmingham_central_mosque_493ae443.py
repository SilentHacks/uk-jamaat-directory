from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
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
    key = "birmingham_central_mosque_493ae443"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("centralmosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://centralmosque.org.uk/timetable",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("fajr", "zuhr", "asr", "maghrib", "isha")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,  # Fajr Jamat
        Prayer.DHUHR: 7,  # Zuhr Jamat
        Prayer.ASR: 9,  # Asr Jamat
        Prayer.MAGHRIB: 11,  # Maghrib Jamat
        Prayer.ISHA: 13,  # Isha Jamat
    }

    def extract(self, ctx: ExtractContext):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            from uk_jamaat_directory.ingest.extract.repo_extractors.contract import ExtractorResult

            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        # Find all tables and pick the one with >20 rows (the actual timetable)
        tables = html_helpers.extract_tables(artifact.text())
        table = None
        for t in tables:
            if len(t.rows) > 20:
                table = t
                break

        if table is None:
            from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
                ExtractorResult,
                ExtractorWarning,
            )

            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no large timetable found",
                        target_label=self.target_label,
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        return self._extract_from_table(ctx, table)

    def accept_row(self, row: list[str], date: datetime) -> bool:
        # Skip legend rows (they have fewer than expected columns)
        return len(row) > 12
