import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
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
    key = "tooting_islamic_centre_47c153c5"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("balhammosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.balhammosque.org/",
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

        # Prayer names and patterns to find
        prayer_patterns = [
            (Prayer.FAJR, r"Fajr"),
            (Prayer.DHUHR, r"Zuhr"),
            (Prayer.ASR, r"Asr"),
            (Prayer.MAGHRIB, r"Maghrib"),
            (Prayer.ISHA, r"Isha"),
        ]

        row_date = datetime.now().date()

        # Extract prayer times from the rendered grid structure
        # Pattern: prayer name followed by begin and jamaat times
        for prayer, prayer_pattern in prayer_patterns:
            # Look for: prayer name, then "Begins" value, then "Jamat" value
            match = re.search(
                rf">\s*{prayer_pattern}\s*<.*?>(\d{{1,2}}:\d{{2}})<.*?>(\d{{1,2}}:\d{{2}})<",
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

        # Canonical prayer order
        order = {
            Prayer.FAJR: 0,
            Prayer.DHUHR: 1,
            Prayer.ASR: 2,
            Prayer.MAGHRIB: 3,
            Prayer.ISHA: 4,
        }
        rows.sort(key=lambda r: (r.date, order.get(r.prayer, 999)))

        return ExtractorResult(rows=rows, warnings=warnings)
