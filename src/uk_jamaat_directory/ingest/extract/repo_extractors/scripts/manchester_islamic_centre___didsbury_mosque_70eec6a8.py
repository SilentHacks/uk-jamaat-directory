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
    key = "manchester_islamic_centre___didsbury_mosque_70eec6a8"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("didsburymosque.com", "didsburymosque.org"))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://didsburymosque.com/prayer-times",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    # We override extract because the source table uses two header rows
    # (grouped names + Begin/Prayer subheaders) with colspans; the parsed
    # data rows are 13 columns wide. We synthesize a logical header aligned
    # to the data so the base column resolver and date logic can be reused.
    date_column = 1
    prayer_columns = {
        Prayer.FAJR: 4,
        Prayer.DHUHR: 7,
        Prayer.ASR: 9,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        for raw_table in html_helpers.extract_tables(html):
            rows = raw_table.rows
            if len(rows) < 3:
                continue
            # Top header row contains the grouped prayer names including "Fajr"
            if html_helpers.header_matches(rows[0], ["fajr", "dhuhr"]):
                # Data starts after the two header rows (row0 grouped, row1 sub)
                body = [list(r) for r in rows[2:]]
                # Align logical header to the 13-col data layout:
                # 0=Day, 1=Date(daynum), 2=Hijri, 3=FajrBegin, 4=FajrJamaat,
                # 5=Sunrise, 6=DhuhrBegin, 7=DhuhrJamaat, 8=AsrBegin, 9=AsrJamaat,
                # 10=Maghrib, 11=IshaBegin, 12=IshaJamaat
                logical_header = [
                    "Day",
                    "Date",
                    "Hijri",
                    "FajrBegin",
                    "Fajr",
                    "Sunrise",
                    "DhuhrBegin",
                    "Dhuhr",
                    "AsrBegin",
                    "Asr",
                    "Maghrib",
                    "IshaBegin",
                    "Isha",
                ]
                effective = html_helpers.Table([logical_header] + body)
                return self._extract_from_table(ctx, effective)
        return ExtractorResult(
            rows=[],
            no_schedule_reason="timetable table not found",
        )
