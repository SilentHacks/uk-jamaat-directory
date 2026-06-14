import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS, coerce_time
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
    key = "al_hidaya_foundation_925dc5ec"
    version = "2026.06.13.3"
    source_match = SourceMatch(domains=("alhidayahfoundation.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://alhidayahfoundation.co.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.body.decode("utf-8", errors="ignore")
        html_clean = html.replace("\n", " ").replace("\r", "")

        # Extract table section
        table_match = re.search(r'<table class="dptTimetable.*?</table>', html_clean, re.DOTALL)
        if not table_match:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")

        table_html = table_match.group(0)

        rows: list[ExtractorRow] = []
        today = datetime.now().date()

        prayer_map = {
            "dhuhr": Prayer.DHUHR,
            "zuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        # Extract rows by matching prayer name + jamah time together
        for match in re.finditer(
            r'<th class="prayerName[^>]*>([^<]+)</th>.*?<td[^>]*class="jamah[^>]*>([^<]+)<',
            table_html,
            re.IGNORECASE | re.DOTALL,
        ):
            prayer_name = match.group(1).strip()
            jamaat_time_str = match.group(2).strip()
            prayer_name_lower = prayer_name.lower()

            # Skip sunrise and fajr
            if prayer_name_lower in ("sunrise", "fajr"):
                continue

            prayer = prayer_map.get(prayer_name_lower)
            if not prayer:
                continue

            # Coerce time with prayer hint for am/pm disambiguation
            jamaat_time = coerce_time(jamaat_time_str, prayer=prayer.value)
            if jamaat_time is None:
                continue

            # Verify time falls within plausible window
            window = PLAUSIBLE_WINDOWS.get(prayer.value)
            if window and not (window[0] <= jamaat_time <= window[1]):
                continue

            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=jamaat_time,
                    start_time=None,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=jamaat_time_str,
                        selector=f"table row for {prayer_name}",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no extractable rows")
        return ExtractorResult(rows=rows)
