import re

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.html import Table
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
    key = "central_jamme_mosque_0e8d09ba"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("readingmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.readingmosque.com/timetable/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 5,
        Prayer.ASR: 7,
        Prayer.MAGHRIB: 8,
        Prayer.ISHA: 10,
    }

    def clean_cell(self, value: str) -> str:
        v = (value or "").strip()
        v = re.sub(r"<[^>]+>", " ", v)
        v = " ".join(v.split())
        # Some cells (e.g. Friday Zuhr Iqamah) contain two times smashed or space-separated
        # like "13:3014:15" or "13:30 14:15". Keep the first plausible time for the jamaat column.
        m = re.match(r"^.*?(\d{1,2}:\d{2}).*", v)
        if m:
            # If it looks like two times glued or listed, take only the first (main jamaat)
            rest = v[m.end(1) :]
            if re.match(r"^\s*\d{1,2}:\d{2}", rest) or re.match(r"^\d{1,2}:\d{2}", rest):
                v = m.group(1)
        return v

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        dpt = None
        for t in tables:
            joined = " ".join(" ".join(r) for r in t.rows).lower()
            if "iqamah" in joined and len(t.rows) > 10:
                dpt = t
                break
        if dpt is None:
            for t in tables:
                if any("iqamah" in (c or "").lower() for c in (t.header or [])):
                    dpt = t
                    break
        if dpt is None:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")
        if len(dpt.rows) < 3:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table has no data rows")
        # Row 0 = grouped headers, row 1 = sub-header with Athan/Iqamah labels.
        # Rebuild Table using sub-header as the header row so base column lookup works.
        subheader = dpt.rows[1]
        data_rows = dpt.rows[2:]
        fixed_rows = [list(subheader)] + [list(r) for r in data_rows]
        norm_table = Table(fixed_rows)
        return self._extract_from_table(ctx, norm_table)
