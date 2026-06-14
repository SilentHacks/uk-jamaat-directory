import re
from datetime import datetime, time

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import times
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    BaseMosqueWebsiteExtractor,
)


class Extractor(BaseMosqueWebsiteExtractor):
    """Extract today's prayer times from the rendered HTML.

    The site shows today's times with Begins (adhan) and 'Iqamah (jamaat)
    columns in plain HTML. The monthly timetable requires AJAX interaction
    that may not occur in headless rendering.
    """

    key = "markazi_jamia_0b6a5061"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("industryroadmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    target_label = "timetable"
    targets = (
        TargetSpec(
            label="timetable",
            url="https://industryroadmosque.com/prayer-times/",
            kind=TargetKind.RENDERED_HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html_text = artifact.text()

        # Look for today's prayer times div with Begins/'Iqamah structure
        # Pattern: <div class="prayer-time prayer-fajr">
        # followed by <div class="prayer-start"> and <div class="prayer-jamaat">

        prayer_map = {
            "prayer-fajr": Prayer.FAJR,
            "prayer-dhuhr": Prayer.DHUHR,
            "prayer-asr": Prayer.ASR,
            "prayer-maghrib": Prayer.MAGHRIB,
            "prayer-isha": Prayer.ISHA,
        }

        # Plausible time windows per prayer (UK context)
        plausible_windows = {
            Prayer.FAJR: (time(2, 0), time(7, 30)),
            Prayer.DHUHR: (time(11, 30), time(16, 0)),
            Prayer.ASR: (time(13, 30), time(20, 0)),
            Prayer.MAGHRIB: (time(15, 30), time(22, 30)),
            Prayer.ISHA: (time(17, 0), time(23, 59)),
        }

        rows = []
        today = datetime.now().date()

        for prayer_class, prayer in prayer_map.items():
            # Find the prayer div
            prayer_div_start = html_text.find(f'<div class="prayer-time {prayer_class}')
            if prayer_div_start == -1:
                continue

            # Find the next closing div
            prayer_div_end = html_text.find("</div> <!-- END of prayer time-->", prayer_div_start)
            if prayer_div_end == -1:
                prayer_div_end = html_text.find("</div>", prayer_div_start + 100)

            prayer_section = html_text[prayer_div_start : prayer_div_end + 20]

            # Extract prayer-start (adhan) - handle multiline div tags
            start_match = re.search(r'<div\s+class="prayer-start"[^>]*>', prayer_section, re.DOTALL)
            jamaat_match = re.search(
                r'<div\s+class="prayer-jamaat"[^>]*>', prayer_section, re.DOTALL
            )

            if not start_match or not jamaat_match:
                continue

            # Extract start time
            start_text_begin = start_match.end()
            start_text_end = prayer_section.find("</div>", start_text_begin)
            start_time_str = prayer_section[start_text_begin:start_text_end].strip()

            # Extract jamaat time
            jamaat_text_begin = jamaat_match.end()
            jamaat_text_end = prayer_section.find("</div>", jamaat_text_begin)
            jamaat_time_str = prayer_section[jamaat_text_begin:jamaat_text_end].strip()

            # Parse times
            try:
                start_time = times.coerce_time(start_time_str, prayer=prayer.value)
                jamaat_time = times.coerce_time(jamaat_time_str, prayer=prayer.value)
            except (ValueError, TypeError):
                continue

            if jamaat_time is None:
                continue

            # Validate jamaat time is in plausible window for this prayer
            window = plausible_windows.get(prayer)
            if window and not (window[0] <= jamaat_time <= window[1]):
                continue

            rows.append(
                ExtractorRow(
                    prayer=prayer,
                    date=today,
                    start_time=start_time,
                    jamaat_time=jamaat_time,
                    evidence=ctx.evidence(
                        target_label=self.target_label,
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=f"Begins: {start_time_str} | Iqamah: {jamaat_time_str}",
                        selector=f".prayer-time.{prayer_class}",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no prayer times found")

        return ExtractorResult(rows=rows)
