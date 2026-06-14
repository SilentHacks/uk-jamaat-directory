from __future__ import annotations

from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
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
    TableTimetableExtractor,
)


class Extractor(TableTimetableExtractor):
    key = "islamic_integration_community_centre_20b933d0"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("iiccuk.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://iiccuk.org/full-year-timetable",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("begins", "jamah")
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
        html = artifact.text()
        month_name = datetime.now().strftime("%B").lower()
        for raw_table in html_helpers.extract_tables(html):
            if not raw_table.rows:
                continue
            title = " ".join(raw_table.rows[0]).lower()
            if month_name not in title:
                continue
            rows = raw_table.rows
            if len(rows) < 4:
                continue
            effective_header = [
                "Day",
                "Fajr Begins",
                "Fajr Jamah",
                "Sunrise",
                "Zuhr Begins",
                "Zuhr Jamah",
                "Asr Begins",
                "Asr Jamah",
                "Magrib Begins",
                "Magrib Jamah",
                "Isha Begins",
                "Isha Jamah",
            ]
            effective = html_helpers.Table([effective_header] + rows[3:])
            return self._extract_from_table(ctx, effective)
        return ExtractorResult(rows=[], no_schedule_reason="no current month timetable found")
