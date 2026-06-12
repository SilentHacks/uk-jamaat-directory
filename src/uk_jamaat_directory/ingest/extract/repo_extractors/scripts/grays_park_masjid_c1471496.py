from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_month_name
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
    key = "grays_park_masjid_c1471496"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("graysparkmasjid.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://graysparkmasjid.co.uk/full-year-timetable",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("day", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 5,
        Prayer.ASR: 7,
        Prayer.MAGHRIB: 9,
        Prayer.ISHA: 11,
    }

    LOGICAL_HEADER = [
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

    def clean_cell(self, value: str) -> str:
        return (value or "").strip()

    def current_year(self, ctx):
        return datetime.now().year

    def current_month(self, ctx):
        return getattr(self, "_forced_month", datetime.now().month)

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        month_tables = []
        for t in tables:
            if not t.rows or not t.rows[0]:
                continue
            first = (t.rows[0][0] or "").strip().lower()
            m = parse_month_name(first)
            if m is not None and len(t.rows) > 3:
                if any("day" in (c or "").lower() for c in t.rows[1]):
                    month_tables.append((m, t))
        if not month_tables:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")
        all_rows = []
        all_warnings = []
        for m, t in month_tables:
            if len(t.rows) < 4:
                continue
            data_rows = [[self.clean_cell(c) for c in r] for r in t.rows[3:]]
            if not data_rows:
                continue
            effective = html_helpers.Table([list(self.LOGICAL_HEADER)] + data_rows)
            self._forced_month = m
            res = self._extract_from_table(ctx, effective)
            self._forced_month = None
            all_warnings.extend(res.warnings or [])
            for r in res.rows:
                if r.prayer == Prayer.DHUHR and r.date.weekday() == 4:
                    all_rows.append(r.model_copy(update={"prayer": Prayer.JUMUAH}))
                else:
                    all_rows.append(r)
        if not all_rows:
            return ExtractorResult(
                rows=[], warnings=all_warnings, no_schedule_reason="no extractable rows"
            )
        all_rows.sort(
            key=lambda r: (
                r.date,
                {
                    Prayer.FAJR: 0,
                    Prayer.DHUHR: 1,
                    Prayer.JUMUAH: 1,
                    Prayer.ASR: 2,
                    Prayer.MAGHRIB: 3,
                    Prayer.ISHA: 4,
                }.get(r.prayer, 99),
                r.session_number,
            )
        )
        return ExtractorResult(rows=all_rows, warnings=all_warnings)
