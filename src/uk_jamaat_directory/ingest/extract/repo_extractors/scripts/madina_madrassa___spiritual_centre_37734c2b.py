from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy, RunFrequency, SourceMatch, TargetKind, TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    TableTimetableExtractor,
)
from uk_jamaat_directory.ingest.extract import helpers


class Extractor(TableTimetableExtractor):
    key = "madina_madrassa___spiritual_centre_37734c2b"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("darassalaam.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://darassalaam.org.uk/prayer-times",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("prayer", "date")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "zuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
    }

    def clean_cell(self, value):
        """Extract time from cell content."""
        if not value:
            return ""
        val = str(value).strip()
        if not val:
            return ""
        # Remove "Begins HH:MM" part and annotations
        if "Begins" in val:
            val = val.split("Begins")[0].strip()
        if "•" in val:
            val = val.split("•")[0].strip()
        val = val.replace("+1mincrease in jamaat time", "").strip()
        for prefix in ["J1 ", "J2 ", "J3 "]:
            if val.startswith(prefix):
                val = val[len(prefix):].strip()
        return helpers.times.coerce_time(val) if val else ""

