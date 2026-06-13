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


class Extractor(BaseMosqueWebsiteExtractor):
    key = "al_furqan_mosque_125c0f6c"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("alfurqanmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://alfurqanmosque.com/prayer-times/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no table found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no table present",
            )

        # Column structure: [Date, Day, Fajr-Begin, Fajr-Iqamah, Sunrise,
        #                    Zuhr-Begin, Zuhr-Iqamah, Asr-Begin, Asr-Iqamah,
        #                    Maghrib-Begin, Maghrib-Iqamah, Isha-Begin, Isha-Iqamah]
        jam_cols = {
            Prayer.FAJR: 3,
            Prayer.DHUHR: 6,
            Prayer.ASR: 8,
            Prayer.MAGHRIB: 10,
            Prayer.ISHA: 12,
        }

        rows_out: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        table = tables[0]
        current_year = datetime.now().year

        for row_idx, row in enumerate(table.rows, start=1):
            if len(row) < 13:
                continue

            date_str = (row[0] or "").strip()
            parsed_date = parse_date_flexible(date_str, default_year=current_year)
            if parsed_date is None:
                warnings.append(
                    ExtractorWarning(
                        code="bad_date",
                        message=f"row {row_idx}: invalid date '{date_str}'",
                        target_label="timetable",
                    )
                )
                continue

            for prayer, col_idx in jam_cols.items():
                if col_idx >= len(row):
                    continue
                time_str = (row[col_idx] or "").strip()
                if not time_str:
                    continue

                jamaat_time = coerce_time(time_str, prayer=prayer.value)
                if jamaat_time is None:
                    warnings.append(
                        ExtractorWarning(
                            code="bad_jamaat",
                            message=f"row {row_idx} {prayer.value}: '{time_str}'",
                            target_label="timetable",
                        )
                    )
                    continue

                session_number = 1
                session_label = None
                if prayer == Prayer.JUMUAH:
                    existing = [
                        r
                        for r in rows_out
                        if r.date == parsed_date and r.prayer == Prayer.JUMUAH
                    ]
                    session_number = len(existing) + 1
                    session_label = f"session {session_number}"

                rows_out.append(
                    ExtractorRow(
                        date=parsed_date,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        session_number=session_number,
                        session_label=session_label,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(row),
                            selector=f"table row {row_idx}",
                        ),
                    )
                )

        if not rows_out:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=rows_out, warnings=warnings)
