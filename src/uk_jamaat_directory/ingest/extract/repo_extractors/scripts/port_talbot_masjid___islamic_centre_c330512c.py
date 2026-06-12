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
    key = "port_talbot_masjid___islamic_centre_c330512c"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("porttalbotmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://porttalbotmosque.org/timetable",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    table_keywords = ("date", "jamaat")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 9,
        Prayer.MAGHRIB: 11,
        Prayer.ISHA: 13,
    }

    def clean_cell(self, value: str) -> str:
        # Strip embedded hijri <p class="hijriDate">...</p> from date cells
        # (and any similar markup) so the flexible date parser receives a
        # clean "June 12, 2026" (or bare day) string.
        v = value
        if "<p" in v.lower() or "dhū" in v.lower() or "hijri" in v.lower():
            if "<" in v:
                v = v.split("<", 1)[0]
            else:
                v = " ".join(v.split()[:3])
        return v.strip()

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        # The /timetable page uses the daily-prayer-time-for-mosques plugin.
        # The monthly table is JS-injected into #monthlyTimetable (via AJAX
        # get_monthly_timetable on select change). The injected table has two
        # header rows: grouped names (Fajr/Zuhr/...) then the actual column
        # headers (Date, Day, Begins, Jamaat, ...). We re-wrap so the sub-header
        # becomes the effective header for the base class.
        for raw_table in html_helpers.extract_tables(html):
            rows = raw_table.rows
            if len(rows) < 2:
                continue
            if html_helpers.header_matches(rows[1], list(self.table_keywords)):
                effective = html_helpers.Table([rows[1]] + rows[2:])
                return self._extract_from_table(ctx, effective)
        # Fallback to standard behaviour (will report "no table" if needed)
        return super().extract(ctx)
