import re
from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    TableTimetableExtractor,
)


class Extractor(TableTimetableExtractor):
    key = "tawheed_islamic_education_centre_of_maidenhead_11b8ff30"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("tiecm.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://tiecm.org/prayer-timetable/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr", "dhuhr", "asr", "maghrib", "isha")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "dhuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
    }

    def clean_cell(self, value: str, prayer: str | None = None) -> str:
        """Split concatenated adhan+iqamah times; extract iqamah (jamaat) time."""
        # Format: "3:03 AMIqm 3:45 AM" → "3:45 AM"
        match = re.search(r'Iqm\s+(\d{1,2}:\d{2}\s*(?:AM|PM))', value, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Fallback: try to extract any time after "Iqm"
        if "iqm" in value.lower():
            parts = re.split(r'iqm\s*', value, flags=re.IGNORECASE)
            if len(parts) > 1:
                return parts[1].strip()
        return value
