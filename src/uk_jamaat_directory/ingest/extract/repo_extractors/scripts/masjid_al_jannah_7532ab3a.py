from __future__ import annotations

import re
from datetime import datetime, time

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
    key = "masjid_al_jannah_7532ab3a"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("aljannah.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer_times",
            url="http://aljannah.org.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("prayer_times")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        text = artifact.text()
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        today_date = datetime.now().date()

        # Extract daily prayer times (FAJR, DHUHR, ASR, MAGHRIB, ISHA)
        # Pattern: <h3>PRAYER_NAME</h3>...Jamaat...time
        prayer_patterns = {
            Prayer.FAJR: (r"<h3>\s*FAJR\s*</h3>.*?<p>(\d{1,2}):(\d{2})\s+(AM|am|PM|pm)</p>", True),
            Prayer.DHUHR: (r"<h3>\s*ZUHR\s*</h3>.*?<p>(\d{1,2}):(\d{2})\s+(AM|am|PM|pm)</p>", True),
            Prayer.ASR: (r"<h3>\s*ASAR\s*</h3>.*?<p>(\d{1,2}):(\d{2})\s+(AM|am|PM|pm)</p>", True),
            Prayer.MAGHRIB: (r"<h3>\s*MAGHRIB\s*</h3>.*?<p>(\d{1,2}):(\d{2})\s+(AM|am|PM|pm)</p>", True),
            Prayer.ISHA: (r"<h3>\s*ISHA\s*</h3>.*?<p>(\d{1,2}):(\d{2})\s+(AM|am|PM|pm)</p>", True),
        }

        for prayer, (pattern, _) in prayer_patterns.items():
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2))
                am_pm = match.group(3).upper()

                # Coerce to proper 24-hour time
                time_str = f"{hour:02d}:{minute:02d}"
                jamaat_time_obj = coerce_time(time_str, prayer=prayer.value)
                if jamaat_time_obj:
                    rows.append(
                        ExtractorRow(
                            date=today_date,
                            prayer=prayer,
                            jamaat_time=jamaat_time_obj,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="prayer_times",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=match.group(0),
                                selector=f"prayer_{prayer.value}",
                            ),
                        )
                    )

        # Extract Jumuah time
        # Pattern: Khuthbah Starts: <b>HH:MM</b>
        jumuah_pattern = r"Khuthbah\s+Starts:\s*<b>(\d{1,2}):(\d{2})</b>"
        match = re.search(jumuah_pattern, text, re.IGNORECASE)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            time_str = f"{hour:02d}:{minute:02d}"
            jamaat_time_obj = coerce_time(time_str, prayer="jumuah")
            if jamaat_time_obj:
                rows.append(
                    ExtractorRow(
                        date=today_date,
                        prayer=Prayer.JUMUAH,
                        jamaat_time=jamaat_time_obj,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="prayer_times",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=match.group(0),
                            selector="jumuah_khutbah",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no jamaat times found",
            )

        return ExtractorResult(rows=rows, warnings=warnings)
