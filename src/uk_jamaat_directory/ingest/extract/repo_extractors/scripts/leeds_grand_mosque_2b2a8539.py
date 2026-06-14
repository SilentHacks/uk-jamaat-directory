from __future__ import annotations

import re
from datetime import date

from uk_jamaat_directory.domain import Prayer
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
    key = "leeds_grand_mosque_2b2a8539"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("leedsgrandmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://leedsgrandmosque.com/prayer",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        rows = []
        today = date.today()

        prayer_map = {
            "fajr": Prayer.FAJR,
            "dhuhr": Prayer.DHUHR,
            "zuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        # Find each prayer block and extract from it
        prayer_block_pattern = r'<div class="rsContent">.*?<span class="prayer-name">(\w+)</span>.*?<span class="date">([^<]+)</span>.*?<span class="jammah">([^<]*)</span>.*?<span class="jammah-date">([^<]*)</span>'

        for match in re.finditer(prayer_block_pattern, html, re.DOTALL):
            prayer_name = match.group(1).lower().strip()
            jammah_str = match.group(4).strip()

            # Skip "shurooq" (sunrise)
            if prayer_name == "shurooq":
                continue

            prayer = prayer_map.get(prayer_name)
            if prayer is None:
                continue

            # Skip if jammah time is empty or "Combined with Maghrib"
            if not jammah_str or jammah_str.lower() == "combined with maghrib":
                continue

            # Parse jammah time
            jammah_time = coerce_time(jammah_str, prayer=prayer_name)
            if jammah_time is None:
                continue

            evidence = ctx.evidence(
                target_label="timetable",
                extractor_key=self.key,
                extractor_version=self.version,
                raw_text=match.group(0),
                selector=f"prayer-name={prayer_name}",
            )

            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=jammah_time,
                    start_time=None,
                    timezone="Europe/London",
                    evidence=evidence,
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no jammah times found",
            )

        return ExtractorResult(rows=rows)
