import re
import json
from datetime import datetime, date

from uk_jamaat_directory.domain import Prayer
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
    """Extract Jamia Sawafia prayer times from masjidbox.com widget."""

    key = "jamia_sawafia_mosque_0054785a"
    version = "2026.06.13.4"
    source_match = SourceMatch(domains=("masjidbox.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/jamia-masjid-swafia",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()

        rows_out: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        today: date = datetime.now().date()

        # Extract REDUX_STATE from the HTML
        redux_match = re.search(r"window\.REDUX_STATE\s*=\s*'([^']+)'", html)
        if not redux_match:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="REDUX_STATE not found",
            )

        try:
            encoded = redux_match.group(1)
            # Simple URL decode: replace %XX with corresponding chars
            decoded = re.sub(r'%([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), encoded)
            data = json.loads(decoded)
        except Exception:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="REDUX_STATE parse failed",
            )

        # Navigate to timetable
        timetable = data.get('masjidbox', {}).get('masjidboxAthany', {}).get('timetable', [])
        if not timetable:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable not found in data",
            )

        # Find today's entry
        today_entry = None
        for day in timetable:
            day_date_str = day.get('date', '')
            try:
                if day_date_str:
                    day_date = datetime.fromisoformat(day_date_str.replace('Z', '+00:00')).date()
                    if day_date == today:
                        today_entry = day
                        break
            except Exception:
                continue

        if not today_entry:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="today not found in timetable",
            )

        # Extract iqamah times
        iqamah = today_entry.get('iqamah', {})
        prayer_mapping = {
            Prayer.FAJR: 'fajr',
            Prayer.DHUHR: 'dhuhr',
            Prayer.ASR: 'asr',
            Prayer.MAGHRIB: 'maghrib',
            Prayer.ISHA: 'isha',
        }

        for prayer, key in prayer_mapping.items():
            time_str = iqamah.get(key)
            if not time_str:
                warnings.append(
                    ExtractorWarning(
                        code="missing_time",
                        message=f"{prayer.value}: not found",
                        target_label="timetable",
                    )
                )
                continue

            # Parse ISO 8601 datetime
            try:
                dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                jamaat_time = dt.time()
            except Exception:
                warnings.append(
                    ExtractorWarning(
                        code="bad_jamaat",
                        message=f"{prayer.value}: '{time_str}'",
                        target_label="timetable",
                    )
                )
                continue

            rows_out.append(
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
                        selector=f"{prayer.value} iqamah",
                    ),
                )
            )

        if not rows_out:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable prayer times",
            )
        return ExtractorResult(rows=rows_out, warnings=warnings)
