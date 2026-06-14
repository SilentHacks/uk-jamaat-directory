from datetime import datetime

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
    key = "makki_masjid_trust_058f83f5"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("makkimasjidburton.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://makkimasjidburton.org.uk/timetable/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
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
        extracted_rows = []
        warnings = []

        # Extract today's date from the page, after "Namaz Timings" to avoid old Ramadan cache
        import re

        # Find the Namaz Timings section first
        namaz_idx = html.find("Namaz Timings")
        if namaz_idx == -1:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_namaz_section",
                        message="Could not find 'Namaz Timings' section",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="namaz timings section not found",
            )

        # Search for dates AFTER Namaz Timings (to avoid old Ramadan cache)
        search_window = html[namaz_idx:]
        date_matches = list(
            re.finditer(r"(\w+),\s+(\d{1,2})(?:st|nd|rd|th)?\s+(\w+),\s+(\d{4})", search_window)
        )

        if not date_matches:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_date_found",
                        message="Could not find date after Namaz Timings",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="date not found",
            )

        # Use the first match after Namaz Timings
        date_match = date_matches[0]
        day_str = date_match.group(2)
        month_str = date_match.group(3)
        year_str = date_match.group(4)
        date_str = f"{day_str} {month_str} {year_str}"

        try:
            parsed_date = parse_date_flexible(date_str, default_year=datetime.now().year)
        except Exception as e:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="date_parse_error",
                        message=f"Failed to parse date '{date_str}': {e}",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="date parsing failed",
            )

        # Extract prayer times from the Namaz Timings section only
        # Format: "Prayer Name Salat:HH:MM AM/PM Time:HH:MM AM/PM"
        namaz_end = html.find("Copyright", namaz_idx)
        if namaz_end == -1:
            namaz_end = len(html)
        namaz_section = html[namaz_idx:namaz_end]
        prayer_pattern = r"(\w+)\s+Salat:([^\s]+\s+[AP]M)\s+Time:([^\s]+\s+[AP]M)"
        prayer_matches = re.findall(prayer_pattern, namaz_section, re.IGNORECASE)

        if not prayer_matches:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_prayers_found",
                        message="No prayer times found in timetable",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no prayer times found",
            )

        for prayer_name, jamaat_str, adhan_str in prayer_matches:
            prayer = None
            session_number = 1
            session_label = None

            prayer_lower = prayer_name.lower()
            if prayer_lower == "fajr":
                prayer = Prayer.FAJR
            elif prayer_lower in ("zuhr", "dhuhr"):
                prayer = Prayer.DHUHR
            elif prayer_lower == "asr":
                prayer = Prayer.ASR
            elif prayer_lower in ("magrib", "maghrib"):
                prayer = Prayer.MAGHRIB
            elif prayer_lower == "isha":
                prayer = Prayer.ISHA
            elif prayer_lower == "jumuah":
                prayer = Prayer.JUMUAH
                # Count Jumuah sessions
                sessions_today = [
                    r for r in extracted_rows if r.date == parsed_date and r.prayer == Prayer.JUMUAH
                ]
                session_number = len(sessions_today) + 1
                session_label = f"session {session_number}"
            else:
                warnings.append(
                    ExtractorWarning(
                        code="unknown_prayer",
                        message=f"Unknown prayer name: {prayer_name}",
                        target_label="timetable",
                    )
                )
                continue

            jamaat_time = coerce_time(jamaat_str)
            start_time = coerce_time(adhan_str)

            if jamaat_time is None:
                warnings.append(
                    ExtractorWarning(
                        code="bad_jamaat_time",
                        message=f"Invalid jamaat time for {prayer_name}: {jamaat_str}",
                        target_label="timetable",
                    )
                )
                continue

            if start_time is None:
                warnings.append(
                    ExtractorWarning(
                        code="bad_start_time",
                        message=f"Invalid start time for {prayer_name}: {adhan_str}",
                        target_label="timetable",
                    )
                )
                continue

            evidence = ctx.evidence(
                target_label="timetable",
                extractor_key=self.key,
                extractor_version=self.version,
                raw_text=f"{prayer_name}: Salat={jamaat_str} Time={adhan_str}",
            )

            extracted_rows.append(
                ExtractorRow(
                    date=parsed_date,
                    prayer=prayer,
                    jamaat_time=jamaat_time,
                    start_time=start_time,
                    session_number=session_number,
                    session_label=session_label,
                    timezone=ctx.timezone,
                    evidence=evidence,
                )
            )

        if not extracted_rows and not warnings:
            warnings.append(
                ExtractorWarning(
                    code="no_extractable_rows",
                    message="Page parsed but no extractable rows found",
                    target_label="timetable",
                )
            )

        return ExtractorResult(rows=extracted_rows, warnings=warnings)
