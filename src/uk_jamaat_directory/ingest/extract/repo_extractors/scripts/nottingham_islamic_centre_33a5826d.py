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


class Extractor(BaseMosqueWebsiteExtractor):
    key = "nottingham_islamic_centre_33a5826d"
    version = "2026.06.13.1"
    source_match = SourceMatch(
        domains=("islamiccentrenottingham.com", "islamiccentrenottingham.org")
    )
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        self._targets = (
            TargetSpec(
                label="timetable",
                url="http://islamiccentrenottingham.com/prayer-times/",
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
                no_schedule_reason="timetable table not found",
            )

        # Find the table with 'Iqamah' in row[0] and then extract the actual iqamah row
        target_table = None
        for table in tables:
            for row in table.rows:
                if row and "iqamah" in row[0].lower() and len(row) > 1:
                    target_table = table
                    break
            if target_table:
                break

        if not target_table:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no iqamah table found",
            )

        # Find the iqamah data row (first column is exactly "Iqamah", not mixed with other text)
        iqamah_row = None
        for row in target_table.rows:
            if row and row[0].strip().lower() == "iqamah":
                iqamah_row = row
                break

        if not iqamah_row:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="iqamah row not found",
            )

        # Map prayer columns: row[1]=Fajr, row[2]=Zuhr, row[3]=Asr, row[4]=Maghrib, row[5]=Isha
        prayer_col_map = {
            Prayer.FAJR: 1,
            Prayer.DHUHR: 2,
            Prayer.ASR: 3,
            Prayer.MAGHRIB: 4,
            Prayer.ISHA: 5,
        }

        parsed_rows = []
        warnings = []
        today = datetime.now().date()

        for prayer, col_idx in prayer_col_map.items():
            raw_time = iqamah_row[col_idx].strip() if col_idx < len(iqamah_row) else ""
            if not raw_time:
                continue

            jamaat = coerce_time(raw_time, prayer=prayer.value)
            if jamaat is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{prayer.value}: {raw_time!r}",
                        target_label="timetable",
                    )
                )
                continue

            parsed_rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    start_time=None,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=raw_time,
                        selector=f"iqamah row col {col_idx}",
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
