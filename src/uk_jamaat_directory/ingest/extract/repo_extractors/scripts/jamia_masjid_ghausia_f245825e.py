import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time, PLAUSIBLE_WINDOWS
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


def _url_decode(encoded: str) -> str:
    """Decode URL-encoded string (%XX format)."""

    def replace_hex(match):
        return chr(int(match.group(1), 16))

    return re.sub(r"%([0-9A-Fa-f]{2})", replace_hex, encoded)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "jamia_masjid_ghausia_f245825e"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("masjidbox.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/jamia-masjid-ghausia",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = (
            artifact.body.decode("utf-8", errors="ignore")
            if isinstance(artifact.body, bytes)
            else artifact.body
        )

        # Extract REDUX_STATE from the HTML
        redux_match = re.search(r'window\.REDUX_STATE\s*=\s*["\']([^"\']*)["\']', html)
        if not redux_match:
            return ExtractorResult(rows=[], no_schedule_reason="could not find REDUX_STATE")

        state_encoded = redux_match.group(1)
        state_json = _url_decode(state_encoded)

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        # Find the timetable array in the JSON
        timetable_start = state_json.find('"timetable":[')
        if timetable_start < 0:
            return ExtractorResult(rows=[], no_schedule_reason="could not find timetable")

        bracket_start = state_json.find("[", timetable_start)
        if bracket_start < 0:
            return ExtractorResult(rows=[], no_schedule_reason="could not find timetable bracket")

        # Find all date entries in the timetable
        date_pattern = r'"date":"(\d{4}-\d{2}-\d{2})T[^"]+"'
        for date_match in re.finditer(date_pattern, state_json[bracket_start:]):
            try:
                date_str = date_match.group(1)
                date_obj = datetime.fromisoformat(date_str).date()
            except (ValueError, AttributeError):
                continue

            # Find the start position of this day's object
            date_start = bracket_start + date_match.start()

            # Find the end of this day's object (next date or end of array)
            date_end = state_json.find('},{"date', date_start + 1)
            if date_end < 0:
                date_end = len(state_json)

            day_obj = state_json[date_start:date_end]

            # Extract prayer times and jamaat (iqamah) times
            prayer_map = {
                "fajr": Prayer.FAJR,
                "dhuhr": Prayer.DHUHR,
                "asr": Prayer.ASR,
                "maghrib": Prayer.MAGHRIB,
                "isha": Prayer.ISHA,
            }

            # Check if this is Friday
            is_friday = date_obj.weekday() == 4

            # Extract iqamah (jamaat) object once per day
            iqamah_match = re.search(r'"iqamah":\{([^}]+)\}', day_obj)
            if not iqamah_match:
                continue

            iqamah_str = iqamah_match.group(1)

            for prayer_key, prayer_enum in prayer_map.items():
                iqamah_pattern = f'"{prayer_key}":"([^"]+)"'
                iqamah_prayer = re.search(iqamah_pattern, iqamah_str)

                if not iqamah_prayer:
                    continue

                try:
                    time_str = iqamah_prayer.group(1)
                    # Extract HH:MM from ISO format: "2026-06-10T03:45:00+01:00"
                    time_match = re.search(r"T(\d{2}):(\d{2})", time_str)
                    if not time_match:
                        continue

                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2))

                    # Convert to time string for coerce_time
                    time_str_coerce = f"{hour}:{minute:02d}"
                    parsed_time = coerce_time(time_str_coerce, prayer=prayer_key)

                    if parsed_time is None:
                        continue

                    # Check plausible window
                    window = PLAUSIBLE_WINDOWS.get(prayer_key)
                    if window and not (window[0] <= parsed_time <= window[1]):
                        warnings.append(
                            ExtractorWarning(
                                code="implausible_time",
                                message=f"{date_obj} {prayer_key}: {time_str_coerce!r} outside plausible window",
                                target_label="timetable",
                            )
                        )
                        continue

                    # Use Jumuah instead of Dhuhr on Friday
                    if is_friday and prayer_enum == Prayer.DHUHR:
                        prayer_enum = Prayer.JUMUAH

                    row = ExtractorRow(
                        date=date_obj,
                        prayer=prayer_enum,
                        jamaat_time=parsed_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{prayer_key}: {time_str_coerce}",
                        ),
                    )
                    rows.append(row)

                except (ValueError, AttributeError):
                    continue

        if not rows:
            return ExtractorResult(
                rows=[], no_schedule_reason="could not extract any prayer times", warnings=warnings
            )

        return ExtractorResult(rows=rows, warnings=warnings)
