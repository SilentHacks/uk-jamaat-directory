from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
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

PRAYER_COLUMNS: dict[Prayer, int] = {
    Prayer.FAJR: 3,
    Prayer.DHUHR: 6,
    Prayer.ASR: 8,
    Prayer.MAGHRIB: 10,
    Prayer.ISHA: 12,
}
START_COLUMNS: dict[Prayer, int] = {
    Prayer.FAJR: 2,
    Prayer.DHUHR: 5,
    Prayer.ASR: 7,
    Prayer.MAGHRIB: 9,
    Prayer.ISHA: 11,
}


class Extractor(BaseMosqueWebsiteExtractor):
    key = "belfast_islamic_centre_6d7e6c26"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("belfastislamiccentre.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        self._targets = (
            TargetSpec(
                label="monthly_timetable",
                url="https://belfastislamiccentre.org.uk/monthly-prayer-times/",
                kind=TargetKind.RENDERED_HTML,
                requires_javascript=True,
            ),
        )
        super().__init__()

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("monthly_timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        tables = extract_tables(artifact.text())
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no table found in monthly timetable HTML",
                        target_label="monthly_timetable",
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        table = tables[0]
        year = datetime.now().year
        parsed_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        for row_number, row in enumerate(table.rows, start=1):
            if len(row) < 13:
                continue

            date_str = row[0].strip()
            if not date_str or "/" not in date_str:
                continue

            try:
                date_obj = datetime.strptime(date_str, "%d/%m/%Y")
            except ValueError:
                warnings.append(
                    ExtractorWarning(
                        code="bad_date",
                        message=f"row {row_number}: unparseable date {date_str!r}",
                        target_label="monthly_timetable",
                    )
                )
                continue

            for prayer, col in PRAYER_COLUMNS.items():
                raw = row[col].strip() if col < len(row) else ""
                if not raw:
                    continue

                jamaat = coerce_time(raw, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{date_str} {prayer.value}: {raw!r}",
                            target_label="monthly_timetable",
                        )
                    )
                    continue

                start = None
                sidx = START_COLUMNS.get(prayer)
                if sidx is not None and sidx < len(row) and row[sidx].strip():
                    start = coerce_time(row[sidx].strip(), prayer=prayer.value)

                parsed_rows.append(
                    ExtractorRow(
                        date=date_obj,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        start_time=start,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="monthly_timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(row),
                            selector=f"table tr:nth-child({row_number})",
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
