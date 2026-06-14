from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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


class Extractor(BaseMosqueWebsiteExtractor):
    key = "norwich_central_mosque___islamic_community_centre_3a933378"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("norwich-central-mosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self):
        super().__init__()
        self._targets = (
            TargetSpec(
                label="timetable",
                url="https://norwich-central-mosque.co.uk/prayer-times/",
                kind=TargetKind.RENDERED_HTML,
                requires_javascript=True,
            ),
        )

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = (
            artifact.body.decode("utf-8", errors="ignore")
            if isinstance(artifact.body, bytes)
            else artifact.body
        )

        # Extract tables
        tables = html_helpers.extract_tables(html)
        if not tables:
            return ExtractorResult(rows=[], no_schedule_reason="no tables found")

        table = tables[0]  # Use first table
        if len(table.rows) < 3:
            return ExtractorResult(rows=[], no_schedule_reason="table too small")

        rows: list[ExtractorRow] = []

        # Column mapping based on table structure:
        # 0: Date, 1: Day, 2: Fajr Begins, 3: Fajr Iqamah, 4: Sunrise,
        # 5: Zuhr Begins, 6: Zuhr Iqamah, 7: Asr Standard, 8: Asr Hanafi, 9: Asr Iqamah,
        # 10: Maghrib Begins, 11: Maghrib Iqamah, 12: Isha Begins, 13: Isha Iqamah

        prayer_cols = {
            Prayer.FAJR: 3,
            Prayer.DHUHR: 6,
            Prayer.ASR: 9,
            Prayer.MAGHRIB: 11,
            Prayer.ISHA: 13,
        }

        current_year = datetime.now().year

        # Process data rows (skip rows 0-1 which are headers)
        for row in table.rows[2:]:
            if len(row) < 14:
                continue

            date_str = row[0].strip()
            if not date_str:
                continue

            try:
                date_obj = parse_date_flexible(date_str, default_year=current_year)
                if not date_obj:
                    continue
            except (ValueError, TypeError):
                continue

            # Extract jamaat times for each prayer
            for prayer, col_idx in prayer_cols.items():
                time_str = row[col_idx].strip()
                if not time_str or time_str in ("–", "-", ""):
                    continue

                jamaat_time = coerce_time(time_str, prayer=prayer.value)
                if jamaat_time is None:
                    continue

                rows.append(
                    ExtractorRow(
                        date=date_obj,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{date_obj} {prayer.value} {time_str}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no prayer times extracted",
            )

        return ExtractorResult(rows=rows)
