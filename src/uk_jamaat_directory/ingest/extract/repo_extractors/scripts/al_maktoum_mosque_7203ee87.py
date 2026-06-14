from __future__ import annotations

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
    key = "al_maktoum_mosque_7203ee87"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("almaktoummosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://almaktoummosque.org/prayer-timetable/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("fajr", "zuhr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 8,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        tables = html_helpers.extract_tables(artifact.text())
        for raw in tables:
            if len(raw.rows) < 3:
                continue
            for candidate_idx in range(min(2, len(raw.rows) - 1)):
                row = raw.rows[candidate_idx]
                row_text = " ".join(row).lower()
                if "date" in row_text and (
                    "iqamah" in row_text or "\u062c\u0645\u0627\u0639\u0629" in row_text
                ):
                    fixed = html_helpers.Table([row] + raw.rows[candidate_idx + 1 :])
                    return self._extract_from_table(ctx, fixed)
        return super().extract(ctx)
