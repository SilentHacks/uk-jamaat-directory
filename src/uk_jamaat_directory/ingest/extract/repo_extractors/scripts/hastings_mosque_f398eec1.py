"""Hastings Mosque timetable extractor."""
import json
import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
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


def _url_unquote(text: str) -> str:
    """Decode URL-encoded string (%XX format) manually."""
    result = []
    i = 0
    while i < len(text):
        if text[i] == '%' and i + 2 < len(text):
            try:
                char_code = int(text[i+1:i+3], 16)
                result.append(chr(char_code))
                i += 3
                continue
            except (ValueError, OverflowError):
                pass
        result.append(text[i])
        i += 1
    return ''.join(result)


class Extractor(BaseMosqueWebsiteExtractor):
    """Extract prayer timetables from Hastings Mosque HTML (MasjidBox embedded data)."""

    key = "hastings_mosque_f398eec1"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("hastingsmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.hastingsmosque.org/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """Extract jamaat times from embedded MasjidBox timetable data."""
        rows: list[ExtractorRow] = []

        # Get the HTML artifact
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="artifact was empty",
            )

        artifact_text = artifact.text()

        # Extract JSON data from the embedded script
        # The timetable is embedded in URL-encoded format: %22="  %3A=: %5B=[  %5D=]
        # Search for "timetable":[{...}]
        match = re.search(r'%22timetable%22%3A(%5B.*?%5D)(?=%2C%22)', artifact_text, re.DOTALL)
        if not match:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable data not found in page",
            )

        try:
            timetable_json = match.group(1)
            # Decode URL encoding manually
            timetable_json = _url_unquote(timetable_json)
            # Parse JSON
            timetable = json.loads(timetable_json)
        except (json.JSONDecodeError, IndexError) as e:
            return ExtractorResult(
                rows=[],
                no_schedule_reason=f"failed to parse timetable JSON: {e}",
            )

        if not isinstance(timetable, list):
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable is not a list",
            )

        for entry in timetable:
            if not isinstance(entry, dict):
                continue

            # Extract date
            date_str = entry.get("date", "")
            if not date_str:
                continue

            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                prayer_date = dt.date()
            except (ValueError, AttributeError):
                continue

            # Extract iqamah (jamaat) times
            iqamah = entry.get("iqamah", {})
            if not isinstance(iqamah, dict):
                continue

            # Check if Jumuah is present (Friday)
            has_jumuah = bool(iqamah.get("jumuah") and isinstance(iqamah.get("jumuah"), list) and len(iqamah.get("jumuah")) > 0)

            # Parse jamaat times for each prayer
            for prayer, time_key in [
                (Prayer.FAJR, "fajr"),
                (Prayer.DHUHR, "dhuhr"),
                (Prayer.ASR, "asr"),
                (Prayer.MAGHRIB, "maghrib"),
                (Prayer.ISHA, "isha"),
            ]:
                # Skip regular DHUHR if Jumuah is present (will use Jumuah instead)
                if prayer == Prayer.DHUHR and has_jumuah:
                    continue

                jamaat_str = iqamah.get(time_key)
                if not jamaat_str:
                    continue

                try:
                    # The jamaat_str is an ISO datetime like "2026-06-13T03:30:00+01:00"
                    # Extract just the time portion
                    dt = datetime.fromisoformat(jamaat_str)
                    jamaat_time = dt.strftime('%H:%M')
                    evidence = ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=jamaat_str,
                        selector=f"$.azan.masjidAzan.item.timetable[?(@.date=='{entry.get('date')}')].iqamah.{time_key}",
                    )
                    rows.append(
                        ExtractorRow(
                            date=prayer_date,
                            prayer=prayer,
                            jamaat_time=jamaat_time,
                            timezone=ctx.timezone,
                            evidence=evidence,
                        )
                    )
                except (ValueError, AttributeError):
                    continue

            # Handle Jumuah (Friday prayer) if present
            if has_jumuah:
                jumuah_str = iqamah.get("jumuah")[0]
                try:
                    # Extract time from ISO datetime
                    dt = datetime.fromisoformat(jumuah_str)
                    jumuah_time = dt.strftime('%H:%M')
                    evidence = ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=jumuah_str,
                        selector=f"$.azan.masjidAzan.item.timetable[?(@.date=='{entry.get('date')}')].iqamah.jumuah[0]",
                    )
                    rows.append(
                        ExtractorRow(
                            date=prayer_date,
                            prayer=Prayer.DHUHR,
                            jamaat_time=jumuah_time,
                            session_label="Jumuah",
                            timezone=ctx.timezone,
                            evidence=evidence,
                        )
                    )
                except (ValueError, AttributeError):
                    continue

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no jamaat times extracted",
            )

        return ExtractorResult(rows=rows)
