from datetime import datetime

from uk_jamaat_directory.domain import Prayer
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
    key = "tunbridge_wells_islamic_cultural_centre_2ecb9500"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("tunbridgewellsmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://tunbridgewellsmosque.com/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        rows = []
        warnings = []
        today = datetime.now().date()

        # Parse daily prayer times from the HTML
        # Expected format (from web inspection):
        # PRAYER | FAJR | SUNRISE | ZUHR | ASR | MAGHRIB | ISHA
        # BEGINS | time | time | time | time | time | time
        # JAMAT  | time | (skip) | time | time | time | time

        # Split HTML into lines and look for the JAMAT line
        import re

        # Pattern: JAMAT followed by exactly 5 times (HH:MM format) in sequence
        # Allow flexibility in whitespace between times
        jamat_pattern = r"JAMAT\s+(\d{1,2}:\d{2})[\s\-\n]+(\d{1,2}:\d{2})[\s\-\n]+(\d{1,2}:\d{2})[\s\-\n]+(\d{1,2}:\d{2})[\s\-\n]+(\d{1,2}:\d{2})"
        match = re.search(jamat_pattern, html, re.IGNORECASE)

        if not match:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_jamat_data",
                        message="JAMAT times not found in HTML",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no jamaat times found",
            )

        # Extract times from the match groups
        # Group order: fajr, zuhr, asr, maghrib, isha
        times_str = match.groups()
        prayers = [
            (Prayer.FAJR, times_str[0]),
            (Prayer.DHUHR, times_str[1]),
            (Prayer.ASR, times_str[2]),
            (Prayer.MAGHRIB, times_str[3]),
            (Prayer.ISHA, times_str[4]),
        ]

        for prayer, time_str in prayers:
            time_str = time_str.strip()
            if time_str and time_str != "-":
                jamaat_time = coerce_time(time_str, prayer=prayer.value)
                if jamaat_time:
                    rows.append(
                        ExtractorRow(
                            date=today,
                            prayer=prayer,
                            jamaat_time=jamaat_time,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=time_str,
                                selector=f"JAMAT {prayer.value}",
                            ),
                        )
                    )
                else:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{prayer.value}: {time_str!r}",
                            target_label="timetable",
                        )
                    )

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings
                if warnings
                else [
                    ExtractorWarning(
                        code="no_extractable_times",
                        message="No extractable prayer times found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no extractable times",
            )

        return ExtractorResult(rows=rows, warnings=warnings)
