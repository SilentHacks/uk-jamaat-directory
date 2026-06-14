from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import Table
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
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers


class Extractor(TableTimetableExtractor):
    key = "finsbury_park_mosque_61064a19"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("finsburyparkmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://finsburyparkmosque.org/prayer-time/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("fajr", "zuhr", "asr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 5,
        Prayer.ASR: 7,
        Prayer.MAGHRIB: 9,
        Prayer.ISHA: 11,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        
        tables = html_helpers.extract_tables(artifact.text())
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no tables found",
                        target_label=self.target_label,
                    )
                ],
                no_schedule_reason="timetable table not found",
            )
        
        # Get the first table. Row 2 has prayer names (with colspan), row 3 has Entry/Jamaà (10 cells)
        # Data rows have 12 cells. Create a synthetic header by expanding the prayer names.
        table_data = tables[0]
        if len(table_data.rows) < 5:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="table_too_short",
                        message="table has fewer than 5 rows",
                        target_label=self.target_label,
                    )
                ],
                no_schedule_reason="timetable table not found",
            )
        
        # Synthetic header based on the HTML structure:
        # June | Fajr Entry | Fajr Jamaà | Sunrise | Zuhr Entry | Zuhr Jamaà | Asr Entry | Asr Jamaà | Maghrib Entry | Maghrib Jamaà | Isha Entry | Isha Jamaà
        header = [
            "date",
            "fajr entry",
            "fajr jamaà",
            "sunrise",
            "zuhr entry",
            "zuhr jamaà",
            "asr entry",
            "asr jamaà",
            "maghrib entry",
            "maghrib jamaà",
            "isha entry",
            "isha jamaà",
        ]
        body = table_data.rows[4:]
        table = Table([header] + body)
        
        return self._extract_from_table(ctx, table)
