from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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

IQAMAH_COLUMNS = {
    Prayer.FAJR: 3,
    Prayer.DHUHR: 6,
    Prayer.ASR: 8,
    Prayer.MAGHRIB: 10,
    Prayer.ISHA: 12,
}


class Extractor(BaseMosqueWebsiteExtractor):
    key = "al_karam_trust_mosque_3ede8482"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("alkaram-mosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self):
        self._targets = (
            TargetSpec(
                label="timetable",
                url="https://www.alkaram-mosque.co.uk/prayer-timetable/",
                kind=TargetKind.RENDERED_HTML,
                requires_javascript=True,
            ),
        )
        super().__init__()

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        tables = extract_tables(artifact.text())
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no table found in timetable HTML",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        table = tables[0]
        parsed_rows = []
        warnings = []

        for row_number, row in enumerate(table.rows, start=1):
            if len(row) < 13:
                continue

            date_str = row[0].strip()
            if not date_str or date_str in ("Date", "June"):
                continue

            row_date = parse_date_flexible(date_str, default_year=datetime.now().year)
            if row_date is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_date",
                        message=f"row {row_number}: {date_str!r}",
                        target_label="timetable",
                    )
                )
                continue

            for prayer, col_idx in IQAMAH_COLUMNS.items():
                if col_idx >= len(row):
                    continue

                raw = row[col_idx].strip()
                if not raw:
                    continue

                jamaat = coerce_time(raw, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue

                parsed_rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
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
