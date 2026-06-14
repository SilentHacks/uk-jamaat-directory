from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
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
    key = "dunstable_masjid_b0ee86ec"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("dunstablemasjid.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://dunstablemasjid.org.uk/monthly",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    table_keywords = ("date", "iqamah")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 8,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }

    def clean_cell(self, value: str) -> str:
        # Strip the embedded hijri paragraph from the date cell so the
        # flexible date parser sees a clean "June 1, 2026" (or bare day) form.
        v = value
        if "<p" in v.lower() or "dhū" in v.lower() or "hijri" in v.lower():
            # keep only the leading date portion before the first < or before hijri text
            if "<" in v:
                v = v.split("<", 1)[0]
            else:
                # fall back to cutting at first non-date token after the day
                v = " ".join(v.split()[:3])
        return v.strip()

    def accept_row(self, row: list[str], row_date: date) -> bool:
        # Drop any row whose present jamaat values (after standard coercion)
        # are not in chronological order. This guards against source data
        # errors (e.g. a single bad "4:12" maghrib cell on the first of the
        # month that coerces inside its window but before the day's Asr).
        coerced: list = []
        for p in (Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA):
            idx = self.prayer_columns.get(p)
            if idx is None or idx >= len(row):
                continue
            raw = row[idx]
            if not raw:
                continue
            t = coerce_time(raw, prayer=p.value)
            if t is not None:
                coerced.append(t)
        if len(coerced) >= 2 and coerced != sorted(coerced):
            return False
        return True

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        # The timetable is JS-injected by the daily-prayer-time plugin into
        # #monthlyTimetable. The rendered DOM contains a table with two
        # header rows: first is grouped names, second has the actual column
        # headers including "Date" / "Day" / "Iqamah" etc.
        # Re-wrap so the sub-header becomes the effective header for the base.
        for raw_table in html_helpers.extract_tables(html):
            rows = raw_table.rows
            if len(rows) < 2:
                continue
            if html_helpers.header_matches(rows[1], list(self.table_keywords)):
                effective = html_helpers.Table([rows[1]] + rows[2:])
                return self._extract_from_table(ctx, effective)
        # Fallback emits the standard "no table" reason
        return super().extract(ctx)
