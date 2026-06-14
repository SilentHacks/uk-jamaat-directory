import re
from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import (
    parse_date_flexible,
    parse_day_of_month,
    parse_month_name,
)
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
    key = "swansea_city_mosque___islamic_community_centre_632517a8"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("swanseamosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://swanseamosque.org/month_view",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr jamah",
        Prayer.DHUHR: "zuhr jamah",
        Prayer.ASR: "asr jamah",
        Prayer.MAGHRIB: "maghrib jamah",
        Prayer.ISHA: "isha jamah",
    }

    def parse_date_cell(self, value: str, *, year: int, month: int) -> date | None:
        cleaned = (value or "").strip()
        if not cleaned:
            return None
        parsed = parse_date_flexible(cleaned, default_year=year)
        if parsed is not None:
            return parsed
        # "01-Jun Mon", "5-Jun", "12-Jun Fri", "01 June" etc.
        m = re.match(r"^(\d{1,2})[- ]([A-Za-z]{3,9})(?:\s+[A-Za-z]{3,9})?$", cleaned)
        if m:
            d = int(m.group(1))
            mon_abbr = m.group(2)
            mon = parse_month_name(mon_abbr)
            if mon is not None:
                try:
                    return date(year, mon, d)
                except ValueError:
                    pass
        day = parse_day_of_month(cleaned)
        if day is not None:
            try:
                return date(year, month, day)
            except ValueError:
                pass
        return None
