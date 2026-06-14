from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS, coerce_time
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
    key = "balham_mosque_204a7555"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("balhammosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://balhammosque.org/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        # React component renders prayer times in a grid structure:
        # <div>Prayer Name</div><div>Start Time</div><div>Jamaat Time</div>
        # Pattern: look for prayer names followed by begin and jamaat times
        prayer_patterns = [
            (Prayer.FAJR, r"Fajr"),
            (Prayer.DHUHR, r"Zuhr"),
            (Prayer.ASR, r"Asr"),
            (Prayer.MAGHRIB, r"Maghrib"),
            (Prayer.ISHA, r"Isha"),
        ]

        row_date = datetime.now().date()

        # Extract the prayer times table structure from the rendered HTML
        # Look for the pattern: prayer name, then times in sequence
        for prayer, prayer_pattern in prayer_patterns:
            # Search for prayer name followed by time values in the grid
            match = re.search(
                rf">{prayer_pattern}</[^>]*>.*?<[^>]*>([0-9:]+)</[^>]*>.*?<[^>]*>([0-9:]+)</[^>]*>",
                html,
                re.DOTALL | re.IGNORECASE,
            )
            if not match:
                continue

            begin_str = match.group(1).strip()
            jamaat_str = match.group(2).strip()

            jamaat = coerce_time(jamaat_str, prayer=prayer.value)
            if jamaat is None:
                continue

            window = PLAUSIBLE_WINDOWS.get(prayer.value)
            if window and not (window[0] <= jamaat <= window[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"{row_date} {prayer.value}: {jamaat_str!r} outside plausible window",
                        target_label="timetable",
                    )
                )
                continue

            start = coerce_time(begin_str, prayer=prayer.value) if begin_str else None

            rows.append(
                ExtractorRow(
                    date=row_date,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    start_time=start,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=f"{prayer.value} | {begin_str} | {jamaat_str}",
                        selector="homepage prayer grid",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no extractable prayer times")

        # Stable order: canonical prayer order for the day
        order = {
            Prayer.FAJR: 0,
            Prayer.DHUHR: 1,
            Prayer.ASR: 2,
            Prayer.MAGHRIB: 3,
            Prayer.ISHA: 4,
        }
        rows.sort(key=lambda r: (r.date, order.get(r.prayer, 999)))

        return ExtractorResult(rows=rows, warnings=warnings)
