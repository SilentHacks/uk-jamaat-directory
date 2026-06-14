import json
import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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
    key = "masjid_quba_66d4fd86"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("alhassan.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://alhassan.org.uk/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        html_content = artifact.text()

        # Extract prayerData JSON from the HTML
        match = re.search(r"const prayerData = (\{.*?\});", html_content, re.DOTALL)
        if not match:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_prayer_data",
                        message="Could not find prayerData JSON in HTML",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="prayerData not found",
            )

        try:
            prayer_data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="invalid_json",
                        message="Failed to parse prayerData JSON",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="JSON parsing failed",
            )

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        current_year = datetime.now().year

        # Iterate through all months and days
        for month_num in range(1, 13):
            month_str = str(month_num)
            if month_str not in prayer_data:
                continue

            month_data = prayer_data[month_str]
            days = month_data.get("days", [])

            for day_info in days:
                day_num = day_info.get("day")
                if not day_num:
                    continue

                # Parse the date
                try:
                    row_date = date(current_year, month_num, day_num)
                except ValueError:
                    continue

                # Extract jamaat times for all five prayers
                prayers_to_extract = [
                    (Prayer.FAJR, "fajrJamat"),
                    (Prayer.DHUHR, "zuhrJamat"),
                    (Prayer.ASR, "asrJamat"),
                    (Prayer.MAGHRIB, "maghribJamat"),
                    (Prayer.ISHA, "ishaJamat"),
                ]

                for prayer, time_key in prayers_to_extract:
                    time_str = day_info.get(time_key)
                    if not time_str or time_str == "-":
                        continue

                    # Coerce time to 24-hour format
                    jamaat_time = coerce_time(time_str, prayer=prayer.value)
                    if jamaat_time is None:
                        warnings.append(
                            ExtractorWarning(
                                code="unparseable_time",
                                message=f"{row_date} {prayer.value}: {time_str!r}",
                                target_label="timetable",
                            )
                        )
                        continue

                    row = ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=time_str,
                            selector=f"prayerData[{month_num}].days[{day_num}].{time_key}",
                        ),
                    )
                    rows.append(row)

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )

        return ExtractorResult(rows=rows, warnings=warnings)
