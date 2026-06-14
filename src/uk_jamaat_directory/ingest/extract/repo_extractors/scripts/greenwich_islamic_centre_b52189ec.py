from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
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
    key = "greenwich_islamic_centre_b52189ec"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("gicuk.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://gicuk.org/timetable/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 7,
        Prayer.ASR: 9,
        Prayer.MAGHRIB: 11,
        Prayer.ISHA: 13,
    }

    def clean_cell(self, value: str) -> str:
        return (value or "").strip()

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        prayer_table = None
        hdr_idx = None
        for t in tables:
            for i, row in enumerate(t.rows):
                if any("date" in c.lower() for c in row):
                    prayer_table = t
                    hdr_idx = i
                    break
            if prayer_table is not None:
                break
        if prayer_table is None or hdr_idx is None:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")
        logical_header = [self.clean_cell(c) for c in prayer_table.rows[hdr_idx]]
        data_rows = [[self.clean_cell(c) for c in r] for r in prayer_table.rows[hdr_idx + 1 :]]
        effective = html_helpers.Table([logical_header] + data_rows)
        res = self._extract_from_table(ctx, effective)
        if not res.rows:
            return res
        adjusted = []
        for r in res.rows:
            if r.prayer == Prayer.DHUHR and r.date.weekday() == 4:
                adjusted.append(r.model_copy(update={"prayer": Prayer.JUMUAH}))
            else:
                adjusted.append(r)
        return ExtractorResult(rows=adjusted, warnings=res.warnings)
