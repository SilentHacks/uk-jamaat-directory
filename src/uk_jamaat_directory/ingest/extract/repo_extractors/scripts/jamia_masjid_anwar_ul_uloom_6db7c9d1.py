from datetime import datetime

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
    key = "jamia_masjid_anwar_ul_uloom_6db7c9d1"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("smethwickjamiamosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        month = now.month
        url = (
            "http://smethwickjamiamosque.co.uk/wp-admin/admin-ajax.php"
            f"?action=get_monthly_timetable&month={month}&display=table"
        )
        self._targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.HTML,
            ),
        )

    @property
    def targets(self):
        return self._targets

    table_keywords = ("date", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 8,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        dpt = None
        for t in tables:
            joined = " ".join(" ".join(r) for r in t.rows).lower()
            if "date" in joined and "iqamah" in joined and len(t.rows) > 5:
                dpt = t
                break
        if dpt is None:
            for t in tables:
                if any("date" in (c or "").lower() for c in (t.header or [])):
                    dpt = t
                    break
        if dpt is None:
            for t in tables:
                if any("iqamah" in (c or "").lower() for c in (t.header or [])) and len(t.rows) > 5:
                    dpt = t
                    break
        if dpt is None:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")
        if len(dpt.rows) < 3:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table has no data rows")
        # Row 0 = grouped headers (Fajr colspan etc), row 1 = sub-header labels with Date/Day/Begins/Iqamah.
        # Rebuild Table using sub-header as the header row so base column lookup (by index) works.
        subheader = dpt.rows[1]
        data_rows = dpt.rows[2:]
        fixed_rows = [list(subheader)] + [list(r) for r in data_rows]
        norm_table = Table(fixed_rows)
        return self._extract_from_table(ctx, norm_table)
