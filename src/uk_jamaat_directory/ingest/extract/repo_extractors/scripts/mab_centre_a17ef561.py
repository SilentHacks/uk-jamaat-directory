import re
from datetime import datetime, timedelta

from uk_jamaat_directory.domain import Prayer
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
    key = "mab_centre_a17ef561"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("muslimhouse.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://muslimhouse.org.uk/",
            kind=TargetKind.RENDERED_HTML,
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
                        message="homepage artifact is empty",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="artifact was empty",
            )

        html_content = artifact.text()

        # Extract jamaat rows: <div class="row bg-info">...label...</div> followed by times in <strong>
        jamaat_pattern = r'<div class="row bg-info">\s*<div class="col-5">(\w+\s+Jamaat)</div>\s*<div class="col"><strong>(\d{2}:\d{2})</strong></div>\s*<div class="col"><strong>(\d{2}:\d{2})</strong></div>'
        matches = re.findall(jamaat_pattern, html_content)

        if not matches:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_jamaat_data",
                        message="no jamaat times found on homepage",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no jamaat times found",
            )

        label_to_prayer = {
            "Fajr Jamaat": Prayer.FAJR,
            "Dhuhr Jamaat": Prayer.DHUHR,
            "Asr Jamaat": Prayer.ASR,
            "Maghrib Jamaat": Prayer.MAGHRIB,
            "Isha Jamaat": Prayer.ISHA,
        }

        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)

        extracted_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        for label, today_time, tomorrow_time in matches:
            prayer = label_to_prayer.get(label)
            if not prayer:
                continue

            # Extract today's time
            jamaat_time_today = parse_time_loose(today_time)
            if jamaat_time_today is None:
                warnings.append(
                    ExtractorWarning(
                        code="bad_time",
                        message=f"could not parse jamaat time '{today_time}' for {label} (today)",
                        target_label="timetable",
                    )
                )
            else:
                evidence = ctx.evidence(
                    target_label="timetable",
                    extractor_key=self.key,
                    extractor_version=self.version,
                    raw_text=f"{label}: {today_time} (today)",
                    selector=f"today {label}",
                )
                extracted_rows.append(
                    ExtractorRow(
                        date=today,
                        prayer=prayer,
                        jamaat_time=jamaat_time_today,
                        timezone=ctx.timezone,
                        evidence=evidence,
                    )
                )

            # Extract tomorrow's time
            jamaat_time_tomorrow = parse_time_loose(tomorrow_time)
            if jamaat_time_tomorrow is None:
                warnings.append(
                    ExtractorWarning(
                        code="bad_time",
                        message=f"could not parse jamaat time '{tomorrow_time}' for {label} (tomorrow)",
                        target_label="timetable",
                    )
                )
            else:
                evidence = ctx.evidence(
                    target_label="timetable",
                    extractor_key=self.key,
                    extractor_version=self.version,
                    raw_text=f"{label}: {tomorrow_time} (tomorrow)",
                    selector=f"tomorrow {label}",
                )
                extracted_rows.append(
                    ExtractorRow(
                        date=tomorrow,
                        prayer=prayer,
                        jamaat_time=jamaat_time_tomorrow,
                        timezone=ctx.timezone,
                        evidence=evidence,
                    )
                )

        if not extracted_rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings or [
                    ExtractorWarning(
                        code="no_rows",
                        message="no jamaat times could be extracted",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no extractable rows",
            )

        return ExtractorResult(rows=extracted_rows, warnings=warnings)
