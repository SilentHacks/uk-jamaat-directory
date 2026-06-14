from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_day_of_month
from uk_jamaat_directory.ingest.extract.helpers.html import find_table
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)

PRAYER_COLUMNS: dict[Prayer, int] = {
    Prayer.FAJR: 3,
    Prayer.DHUHR: 6,
    Prayer.ASR: 8,
    Prayer.MAGHRIB: 9,
    Prayer.ISHA: 11,
}


class Extractor(BaseMosqueWebsiteExtractor):
    key = "faizan_e_madinah_aa66ad66"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("langleymasjid.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.langleymasjid.com/prayer-timetable/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        table = find_table(artifact.text(), header_keywords=["fajr", "zuhr", "maghrib"])
        if table is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable table not found",
            )

        year = datetime.now().year
        month = datetime.now().month
        rows: list[ExtractorRow] = []
        # table.header is row 0; table.body() is rows 1+ (includes 2nd header
        # row "June Day Start Jamaat ..." which is skipped via date parse).
        for row_number, row in enumerate(table.body(), start=2):
            if not row or len(row) < 12:
                continue
            day = parse_day_of_month(row[0].strip())
            if day is None:
                continue
            try:
                row_date = date(year, month, day)
            except ValueError:
                continue
            for prayer, col in PRAYER_COLUMNS.items():
                raw = row[col].strip() if col < len(row) else ""
                if not raw:
                    continue
                jamaat = coerce_time(raw, prayer=prayer.value)
                if jamaat is None:
                    continue
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(c.strip() for c in row),
                            selector=f"table row {row_number}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=rows)
