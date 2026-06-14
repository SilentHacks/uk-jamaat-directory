import re
from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import MONTHS
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
    key = "swansea_city_mosque___islamic_community_centre_b6c6832e"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("swanseamosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://swanseamosque.org/month_view",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr jamah", "zuhr jamah")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr jamah",
        Prayer.DHUHR: "zuhr jamah",
        Prayer.ASR: "asr jamah",
        Prayer.MAGHRIB: "maghrib jamah",
        Prayer.ISHA: "isha jamah",
    }

    def parse_date_cell(self, value: str, *, year: int, month: int) -> date | None:
        # Parse format like "01-Jun Mon" -> remove weekday, parse day-month
        cleaned = value.rsplit(maxsplit=1)[0]  # Remove weekday
        # Parse day-month format: "01-Jun" or "1-Jun"
        m = re.match(r"^(\d{1,2})-([a-zA-Z]{3,})", cleaned)
        if m:
            try:
                day = int(m.group(1))
                month_name = m.group(2).lower()
                parsed_month = MONTHS.get(month_name)
                if parsed_month and 1 <= day <= 31:
                    return date(year, parsed_month, day)
            except ValueError:
                pass
        return None
