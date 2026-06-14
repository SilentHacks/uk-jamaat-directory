import re

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
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
    key = "al_madinah_masjid_d9c8e11d"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("almadinahmasjid.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://almadinahmasjid.co.uk/time-table/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("fajr", "zuhr", "asr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 8,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }

    def clean_cell(self, value: str) -> str:
        v = value.strip()
        # The date cells contain glued hijri <p> suffix from the HTML parser;
        # strip everything after the first date token so numeric date regex matches.
        v = re.sub(r"\s*<.*$", "", v).strip()
        v = re.sub(r"<[^>]+>", "", v).strip()
        # Keep only the leading DD/MM/YYYY-ish token if extra text remains
        m = re.match(r"^(\d{1,2}[/\-.]\d{1,2}(?:[/\-.]\d{2,4})?)", v)
        if m:
            v = m.group(1)
        return v

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        tables = html_helpers.extract_tables(artifact.text())
        for raw_table in tables:
            if len(raw_table.rows) < 3:
                continue
            # Detect the column header row (second row) which contains the real labels
            col_header = [c.lower() for c in raw_table.rows[1]]
            if (
                "date" in col_header
                and "day" in col_header
                and any("iqamah" in c for c in col_header)
            ):
                synthetic_rows = [raw_table.rows[1]] + raw_table.rows[2:]
                synthetic = html_helpers.Table(synthetic_rows)
                return self._extract_from_table(ctx, synthetic)
        return ExtractorResult(
            rows=[],
            warnings=[
                ExtractorWarning(
                    code="no_table",
                    message="no dpt monthly timetable structure found",
                    target_label=self.target_label,
                )
            ],
            no_schedule_reason="timetable table not found",
        )
