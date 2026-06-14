import json
import re
from datetime import datetime

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
    key = "masjid_khadijah_and_islamic_centre_1e1c5e1e"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("ukimpeterborough.org.uk", "masjidbox.com"))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="masjidbox_timetable",
            url="https://masjidbox.com/prayer-times/khadijah",
            kind=TargetKind.RENDERED_HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        body = ctx.artifact("masjidbox_timetable")
        if not body.body:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="empty_artifact",
                        message="masjidbox_timetable artifact is empty",
                        target_label="masjidbox_timetable",
                    )
                ],
                no_schedule_reason="artifact was empty",
            )

        html = body.text()
        extracted_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        # Extract JSON-LD prayer event data from the page
        json_ld_pattern = r'<script type="application/ld\+json">\[(.*?)\]</script>'
        match = re.search(json_ld_pattern, html, re.DOTALL)

        if not match:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_json_ld",
                        message="no JSON-LD prayer event data found",
                        target_label="masjidbox_timetable",
                    )
                ],
                no_schedule_reason="no JSON-LD structured data",
            )

        try:
            events_json = "[" + match.group(1) + "]"
            events = json.loads(events_json)
        except (json.JSONDecodeError, IndexError):
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="json_parse_error",
                        message="failed to parse JSON-LD prayer events",
                        target_label="masjidbox_timetable",
                    )
                ],
                no_schedule_reason="JSON-LD parsing failed",
            )

        if not events:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_events",
                        message="no prayer events in JSON-LD data",
                        target_label="masjidbox_timetable",
                    )
                ],
                no_schedule_reason="no events found",
            )

        jumuah_count = 0

        for event in events:
            if not isinstance(event, dict):
                continue

            # Extract prayer type from event name (e.g., "🕌 Fajr Prayer → 2:57 AM")
            name = event.get("name", "")
            prayer_match = re.search(r"(fajr|sunrise|dhuhr|asr|maghrib|isha|jumuah)", name.lower())
            if not prayer_match:
                continue

            prayer_name = prayer_match.group(1)

            # Skip sunrise (not a jamaat prayer)
            if prayer_name == "sunrise":
                continue

            # Extract start time from the ISO format startDate
            start_date_str = event.get("startDate", "")
            if not start_date_str:
                warnings.append(
                    ExtractorWarning(
                        code="no_start_date",
                        message=f"no startDate for {prayer_name}",
                        target_label="masjidbox_timetable",
                    )
                )
                continue

            try:
                # Parse ISO format: "2026-06-13T02:57:00+01:00"
                dt = datetime.fromisoformat(start_date_str)
                date = dt.date()
                time_str = dt.strftime("%I:%M %p")
            except (ValueError, AttributeError):
                warnings.append(
                    ExtractorWarning(
                        code="bad_datetime",
                        message=f"could not parse startDate for {prayer_name}: {start_date_str}",
                        target_label="masjidbox_timetable",
                    )
                )
                continue

            jamaat_time = parse_time_loose(time_str)
            if not jamaat_time:
                warnings.append(
                    ExtractorWarning(
                        code="bad_time",
                        message=f"could not parse time for {prayer_name}: {time_str}",
                        target_label="masjidbox_timetable",
                    )
                )
                continue

            prayer = parse_prayer_label(prayer_name)
            if not prayer:
                continue

            session_number = 1
            session_label = None
            if prayer.value == "jumuah":
                jumuah_count += 1
                session_number = jumuah_count
                session_label = f"session {session_number}"

            evidence = ctx.evidence(
                target_label="masjidbox_timetable",
                extractor_key=self.key,
                extractor_version=self.version,
                raw_text=f"{prayer_name}: {time_str}",
                selector="script[type='application/ld+json']",
            )

            extracted_rows.append(
                ExtractorRow(
                    date=date,
                    prayer=prayer,
                    jamaat_time=jamaat_time,
                    session_number=session_number,
                    session_label=session_label,
                    timezone=ctx.timezone,
                    evidence=evidence,
                )
            )

        if not extracted_rows:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_extractable_rows",
                        message="no valid prayer times extracted from events",
                        target_label="masjidbox_timetable",
                    )
                ],
                no_schedule_reason="no extractable prayer times",
            )

        return ExtractorResult(rows=extracted_rows, warnings=warnings)
