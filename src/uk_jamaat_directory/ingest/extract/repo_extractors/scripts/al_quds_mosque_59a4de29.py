from datetime import date, timedelta

from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
from uk_jamaat_directory.ingest.extract.helpers.times import parse_time_loose
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
    """Brighton Mosque Ramadan timetable: prayer-only table (no date column)."""

    key = "al_quds_mosque_59a4de29"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("brightonmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://brightonmosque.com/ramadan-2025-time-table/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
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

        html = artifact.text()
        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no table found in artifact",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no table present",
            )

        table = tables[0]
        table_rows = list(table.body())
        if not table_rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="table is empty",
            )

        extracted_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        # Ramadan 2026: approximately mid-May to mid-June
        # (The site publishes Ramadan 2025 data; we apply it to Ramadan 2026)
        ramadan_start = date(2026, 5, 23)

        for row_index, row in enumerate(table_rows, start=1):
            if len(row) < 3:
                continue

            prayer_text = row[0].strip()
            prayer = parse_prayer_label(prayer_text)
            if prayer is None:
                continue

            jamaat_time = parse_time_loose(row[2].strip()) if len(row) > 2 else None
            start_time = parse_time_loose(row[1].strip()) if len(row) > 1 else None

            if jamaat_time is None:
                warnings.append(
                    ExtractorWarning(
                        code="bad_jamaat",
                        message=f"row {row_index} ({prayer_text}): invalid jamaat time '{row[2] if len(row) > 2 else ''}'",
                        target_label="timetable",
                    )
                )
                continue

            # Emit one row per day of Ramadan
            for day_offset in range(30):
                row_date = ramadan_start + timedelta(days=day_offset)
                evidence = ctx.evidence(
                    target_label="timetable",
                    extractor_key=self.key,
                    extractor_version=self.version,
                    raw_text=" | ".join(row),
                    selector=f"table tbody tr:nth-child({row_index})",
                )
                extracted_rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        start_time=start_time,
                        timezone=ctx.timezone,
                        evidence=evidence,
                    )
                )

        if not extracted_rows and not warnings:
            warnings.append(
                ExtractorWarning(
                    code="no_extractable_rows",
                    message="table parsed but no extractable rows",
                    target_label="timetable",
                )
            )

        return ExtractorResult(rows=extracted_rows, warnings=warnings)
