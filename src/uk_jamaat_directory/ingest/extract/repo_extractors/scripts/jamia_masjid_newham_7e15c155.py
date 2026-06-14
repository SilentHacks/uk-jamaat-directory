import json
import re
from datetime import date, time

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
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
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    BaseMosqueWebsiteExtractor,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "jamia_masjid_newham_7e15c155"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("masjidbox.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="masjidbox prayer times",
            url="https://masjidbox.com/prayer-times/markazi-jamia-masjid-newham",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """Extract prayer times from masjidbox embedded widget HTML."""
        rows = []
        warnings = []

        try:
            artifact = ctx.artifact("masjidbox prayer times")
        except KeyError:
            return ExtractorResult(
                no_schedule_reason="Target artifact not found",
                warnings=[
                    ExtractorWarning(code="missing_artifact", message="Target artifact not found")
                ],
            )

        html = artifact.body.decode("utf-8", errors="replace")

        try:
            # Extract REDUX_STATE JSON from HTML
            match = re.search(r"window\.REDUX_STATE = '([^']+)'", html)
            if not match:
                return ExtractorResult(
                    no_schedule_reason="REDUX_STATE not found",
                    warnings=[
                        ExtractorWarning(
                            code="parse_failed",
                            message="REDUX_STATE JSON not found in HTML",
                            target_label="masjidbox prayer times",
                        )
                    ],
                )

            # Percent-decode JSON: replace %XX hex sequences
            encoded = match.group(1)
            decoded = ""
            i = 0
            while i < len(encoded):
                if encoded[i] == "%" and i + 2 < len(encoded):
                    try:
                        hex_str = encoded[i + 1 : i + 3]
                        decoded += chr(int(hex_str, 16))
                        i += 3
                    except (ValueError, OverflowError):
                        decoded += encoded[i]
                        i += 1
                else:
                    decoded += encoded[i]
                    i += 1

            data = json.loads(decoded)
            timetable = data.get("masjidbox", {}).get("masjidboxAthany", {}).get("timetable", [])

            if not timetable:
                return ExtractorResult(
                    no_schedule_reason="No timetable data found",
                    warnings=[
                        ExtractorWarning(
                            code="no_data",
                            message="Timetable data not found in response",
                            target_label="masjidbox prayer times",
                        )
                    ],
                )

            # Extract prayer times for each day
            for day_data in timetable:
                date_str = day_data.get("date", "").split("T")[0]
                if not date_str:
                    continue

                try:
                    row_date = date.fromisoformat(date_str)
                except (ValueError, TypeError):
                    continue

                iqamah = day_data.get("iqamah", {})

                # Daily prayers (use iqamah times as jamaat)
                prayers = [
                    ("fajr", Prayer.FAJR),
                    ("dhuhr", Prayer.DHUHR),
                    ("asr", Prayer.ASR),
                    ("maghrib", Prayer.MAGHRIB),
                    ("isha", Prayer.ISHA),
                ]

                for key, prayer_type in prayers:
                    iqamah_time = iqamah.get(key)
                    if iqamah_time:
                        try:
                            # Extract time portion (HH:MM) from ISO format
                            time_str = iqamah_time.split("T")[1].split("+")[0][:5]  # HH:MM
                            t = time.fromisoformat(time_str)
                            evidence = ctx.evidence(
                                target_label="masjidbox prayer times",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=iqamah_time,
                            )
                            rows.append(
                                ExtractorRow(
                                    date=row_date,
                                    prayer=prayer_type,
                                    jamaat_time=t,
                                    evidence=evidence,
                                )
                            )
                        except (ValueError, IndexError):
                            pass

                # Jumuah times (Friday)
                hijri = day_data.get("hijri", {})
                day_name = hijri.get("day", "")
                if "الجمعة" in day_name:  # Friday in Arabic
                    jumuah_times = iqamah.get("jumuah", [])
                    for jumuah_time in jumuah_times:
                        try:
                            time_str = jumuah_time.split("T")[1].split("+")[0][:5]  # HH:MM
                            t = time.fromisoformat(time_str)
                            evidence = ctx.evidence(
                                target_label="masjidbox prayer times",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=jumuah_time,
                            )
                            rows.append(
                                ExtractorRow(
                                    date=row_date,
                                    prayer=Prayer.JUMUAH,
                                    jamaat_time=t,
                                    evidence=evidence,
                                )
                            )
                        except (ValueError, IndexError):
                            pass

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            warnings.append(
                ExtractorWarning(
                    code="extraction_error",
                    message=f"Error parsing data: {str(e)}",
                    target_label="masjidbox prayer times",
                )
            )

        if not rows:
            return ExtractorResult(
                no_schedule_reason="No prayer times extracted from timetable",
                warnings=warnings
                if warnings
                else [
                    ExtractorWarning(
                        code="no_rows",
                        message="No rows extracted from timetable",
                        target_label="masjidbox prayer times",
                    )
                ],
            )

        return ExtractorResult(rows=rows, warnings=warnings)
