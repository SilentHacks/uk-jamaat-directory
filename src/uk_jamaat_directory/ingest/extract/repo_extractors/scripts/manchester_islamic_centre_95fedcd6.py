from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
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


class Extractor(BaseMosqueWebsiteExtractor):
    key = "manchester_islamic_centre_95fedcd6"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("nasfatmanchester.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://nasfatmanchester.org.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        body = ctx.artifact("timetable")
        if not body.body:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="empty_artifact",
                        message="timetable artifact is empty",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="artifact was empty",
            )
        html = body.text()
        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no prayer table found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no table present",
            )

        warnings: list[ExtractorWarning] = []
        extracted_rows: list[ExtractorRow] = []

        for table_idx, table in enumerate(tables):
            header = [cell.strip().lower() for cell in table.header]
            if not ("salat" in " ".join(header) or "name" in " ".join(header)):
                continue

            rows = list(table.body())
            if not rows:
                continue

            for row_idx, row in enumerate(rows):
                if len(row) < 3:
                    continue
                prayer_cell = row[0].strip()
                prayer = parse_prayer_label(prayer_cell)
                if prayer is None:
                    continue

                jamaat_cell = row[2].strip() if len(row) > 2 else ""
                if not jamaat_cell:
                    continue

                jamaat_time = coerce_time(jamaat_cell, prayer=prayer.value)
                if jamaat_time is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{prayer.value}: {jamaat_cell!r}",
                            target_label="timetable",
                        )
                    )
                    continue

                row_date = datetime.now().date()
                extracted_rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{prayer_cell} | {jamaat_cell}",
                            selector=f"table tbody tr:nth-child({row_idx + 1})",
                        ),
                    )
                )

        if not extracted_rows:
            if not warnings:
                warnings.append(
                    ExtractorWarning(
                        code="no_rows",
                        message="no prayer times found",
                        target_label="timetable",
                    )
                )
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )

        return ExtractorResult(rows=extracted_rows, warnings=warnings)
