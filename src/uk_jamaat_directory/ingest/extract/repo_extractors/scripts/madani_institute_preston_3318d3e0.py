from __future__ import annotations

import re
from datetime import date

from uk_jamaat_directory.domain import Prayer
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
    key = "madani_institute_preston_3318d3e0"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("mamissionuk.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/ma-mission-learning-centre",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
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
        today = date.today()
        extracted_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        # Parse prayer times from rendered masjidbox HTML
        # Structure: pairs of elements like [prayer label, adhan time, iqamah label, iqamah time]
        # or similar layout with uppercase prayer names and times
        prayer_map = {
            "Fajr": Prayer.FAJR,
            "Dhuhr": Prayer.DHUHR,
            "Asr": Prayer.ASR,
            "Maghrib": Prayer.MAGHRIB,
            "Isha": Prayer.ISHA,
            "Jumuah": Prayer.JUMUAH,
        }

        # Extract all time patterns: HH:MM followed by optional AM/PM
        times_with_labels = re.findall(
            r"([A-Z][a-z]+)(?:\s|^)(\d{1,2}):(\d{2})(?:(?:\s|^)(AM|PM))?", html
        )

        session_counts = {}
        for label, hour, minute, ampm in times_with_labels:
            prayer = prayer_map.get(label)
            if not prayer:
                continue

            try:
                time_str = f"{hour}:{minute}"
                if ampm:
                    time_str += f" {ampm}"
                jamaat_time = parse_time_loose(time_str)
                if not jamaat_time:
                    continue

                session_number = 1
                session_label: str | None = None
                if prayer.value == "jumuah":
                    if prayer not in session_counts:
                        session_counts[prayer] = 0
                    session_counts[prayer] += 1
                    session_number = session_counts[prayer]
                    session_label = f"session {session_number}"

                evidence = ctx.evidence(
                    target_label="timetable",
                    extractor_key=self.key,
                    extractor_version=self.version,
                    raw_text=f"{label} {hour}:{minute}" + (f" {ampm}" if ampm else ""),
                    selector=f"prayer-time[prayer='{label}']",
                )
                extracted_rows.append(
                    ExtractorRow(
                        date=today,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        start_time=None,
                        session_number=session_number,
                        session_label=session_label,
                        timezone=ctx.timezone,
                        evidence=evidence,
                    )
                )
            except (ValueError, AttributeError):
                warnings.append(
                    ExtractorWarning(
                        code="parse_error",
                        message=f"failed to parse {label} time",
                        target_label="timetable",
                    )
                )
                continue

        if not extracted_rows:
            warnings.append(
                ExtractorWarning(
                    code="no_extractable_rows",
                    message="no extractable prayer times found in rendered HTML",
                    target_label="timetable",
                )
            )
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable prayer times found",
            )
        return ExtractorResult(rows=extracted_rows, warnings=warnings)
