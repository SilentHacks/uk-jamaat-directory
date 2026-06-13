import json
import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
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


def _url_decode(encoded: str) -> str:
    """Manual URL decoding for %XX sequences."""
    result = []
    i = 0
    while i < len(encoded):
        if encoded[i] == '%' and i + 2 < len(encoded):
            hex_str = encoded[i+1:i+3]
            try:
                result.append(chr(int(hex_str, 16)))
                i += 3
            except ValueError:
                result.append(encoded[i])
                i += 1
        elif encoded[i] == '+':
            result.append(' ')
            i += 1
        else:
            result.append(encoded[i])
            i += 1
    return ''.join(result)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "lea_bridge_road_mosque_75d5f9ab"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("wfia.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/wfialondon",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """Extract jamaat times from MasjidBox HTML timetable widget."""
        rows = []
        artifact = ctx.artifact("timetable")
        content = artifact.text()

        # Extract JSON data embedded in the HTML
        match = re.search(r"window\.REDUX_STATE\s*=\s*'([^']+)'", content)
        if not match:
            return ExtractorResult(no_schedule_reason="Could not find timetable data in page")

        try:
            # URL-decode the encoded string, then parse JSON
            encoded = match.group(1)
            decoded = _url_decode(encoded)
            data = json.loads(decoded)

            timetable = data.get("masjidbox", {}).get("masjidboxAthany", {}).get("timetable", [])

            for entry in timetable:
                date_str = entry.get("date", "")
                if not date_str:
                    continue

                # Parse the date - format is "YYYY-MM-DDTHH:MM:SS HH:MM" (with space before offset)
                # Convert to ISO format with + instead of space
                date_str_normalized = date_str.replace(" ", "+")
                date_obj = datetime.fromisoformat(date_str_normalized)

                iqamah = entry.get("iqamah", {})

                # Regular prayers with iqamah
                for prayer_name, prayer_enum in [
                    ("fajr", Prayer.FAJR),
                    ("dhuhr", Prayer.DHUHR),
                    ("asr", Prayer.ASR),
                    ("maghrib", Prayer.MAGHRIB),
                    ("isha", Prayer.ISHA),
                ]:
                    if iqamah.get(prayer_name):
                        time_str = iqamah[prayer_name].replace(" ", "+")
                        prayer_time = datetime.fromisoformat(time_str)
                        rows.append(
                            ExtractorRow(
                                date=date_obj.date(),
                                prayer=prayer_enum,
                                jamaat_time=prayer_time.time(),
                                evidence=ctx.evidence(
                                    target_label="timetable",
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    selector=f"iqamah.{prayer_name}",
                                ),
                            )
                        )

        except (json.JSONDecodeError, KeyError, ValueError, AttributeError) as e:
            return ExtractorResult(no_schedule_reason=f"Failed to parse timetable: {type(e).__name__}")

        if not rows:
            return ExtractorResult(no_schedule_reason="No jamaat times found in timetable")

        return ExtractorResult(rows=rows)
