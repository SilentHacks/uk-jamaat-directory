import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    ExtractorWarning,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)

PRAYER_COLUMNS = {
    Prayer.FAJR: 3,
    Prayer.DHUHR: 6,
    Prayer.ASR: 9,
    Prayer.MAGHRIB: 11,
    Prayer.ISHA: 13,
}


class Extractor(BaseMosqueWebsiteExtractor):
    key = "al_emaan_centre_fa0f95b4"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("al-emaan.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://al-emaan.org.uk/prayer-times/",
            kind=TargetKind.HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        if "</table>" not in html and "<table" in html:
            html = html + "</table>"

        tables = html_helpers.extract_tables(html)

        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no tables found in HTML",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no tables found",
            )

        table = tables[0]
        all_rows = table.rows

        if len(all_rows) < 3:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="insufficient_rows",
                        message="table has fewer than 3 rows",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="table too small",
            )

        warnings: list[ExtractorWarning] = []
        parsed_rows: list[ExtractorRow] = []
        year = datetime.now().year
        month = datetime.now().month

        for row_idx, row in enumerate(all_rows[2:], start=1):
            if len(row) < 14:
                continue

            date_str = row[0].strip()
            if not date_str or date_str.lower() == "date":
                continue

            day_match = re.match(r"(\d+)", date_str)
            day = None
            if day_match:
                try:
                    day = int(day_match.group(1))
                except (ValueError, IndexError):
                    pass

            if day is None or day < 1 or day > 31:
                warnings.append(
                    ExtractorWarning(
                        code="bad_date",
                        message=f"could not parse date {date_str!r}",
                        target_label="timetable",
                    )
                )
                continue

            try:
                row_date = date(year, month, day)
            except ValueError:
                continue

            for prayer, col_idx in PRAYER_COLUMNS.items():
                if col_idx >= len(row):
                    continue

                raw_time = row[col_idx].strip()
                if not raw_time:
                    continue

                jamaat = coerce_time(raw_time, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {raw_time!r}",
                            target_label="timetable",
                        )
                    )
                    continue

                parsed_rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        start_time=None,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{prayer.value}: {raw_time}",
                            selector=f"table row {row_idx}",
                        ),
                    )
                )

        if not parsed_rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )

        return ExtractorResult(rows=parsed_rows, warnings=warnings)
