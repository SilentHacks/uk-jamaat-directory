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
    key = "islamic_centre_upton_park_c551527c"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("masjidalhikmah.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidalhikmah.co.uk/salah-times",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 4,
        Prayer.ASR: 6,
        Prayer.MAGHRIB: 8,
        Prayer.ISHA: 10,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        tables = html_helpers.extract_tables(artifact.text())
        for raw in tables:
            wide_rows = [r for r in raw.rows if len(r) >= 11]
            if not wide_rows:
                continue
            flat = " ".join(" ".join(r) for r in raw.rows).lower()
            if "date" not in flat or "jama" not in flat:
                continue
            # synthetic header wide enough for integer column indices (0..10)
            synthetic_header = ["Date"] + [f"c{i}" for i in range(10)]
            fixed = html_helpers.Table([synthetic_header] + wide_rows)
            return self._extract_from_table(ctx, fixed)
        return ExtractorResult(
            rows=[],
            warnings=[],
            no_schedule_reason="timetable table not found",
        )
