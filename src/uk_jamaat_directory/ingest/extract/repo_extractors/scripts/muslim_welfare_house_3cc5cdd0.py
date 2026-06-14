from uk_jamaat_directory.domain import Prayer
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
    key = "muslim_welfare_house_3cc5cdd0"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("mwht.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://mwht.org.uk/prayer-time/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("fajr", "asr", "zuhr")
    date_column = 0

    # Column indices based on the layout:
    # Row 1: June | Fajr | Sunrise | Zuhr | Asr | Magrib | Isha
    # Row 2: Entry | Jamaà | Entry | Jamaà | Entry | Jamaà | Entry | Jamaà
    # Data rows: date | entry(fajr) | jamaà(fajr) | sunrise | entry(zuhr) | jamaà(zuhr) | entry(asr) | jamaà(asr) | entry(magrib) | jamaà(magrib) | entry(isha) | jamaà(isha)
    # So jamaat columns are: 2 (fajr), 5 (zuhr), 7 (asr), 9 (magrib), 11 (isha)

    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 5,
        Prayer.ASR: 7,
        Prayer.MAGHRIB: 9,
        Prayer.ISHA: 11,
    }

    def accept_row(self, row: list[str], row_date) -> bool:
        date_val = row[self.date_column].strip() if self.date_column < len(row) else ""
        if not date_val or date_val in ("June",):
            return False
        try:
            int(date_val)
            return True
        except ValueError:
            return False
