"""
Shahparan Chadderton Central Mosque prayer timetable extractor.
Source: https://chaddertonshahporan.co.uk/

The mosque website is a JavaScript-rendered SPA with no server-side HTML tables.
Prayer times are loaded dynamically by the Vue.js application and require
browser automation to access. This extractor is stubbed pending JavaScript
rendering infrastructure.
"""

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
    key = "shahparan_chadderton_central_mosque_72a67300"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("chaddertonshahporan.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://chaddertonshahporan.co.uk/",
            kind=TargetKind.RENDERED_HTML,
        ),
    )
    requires_javascript = True
    table_keywords = ("prayer", "time", "fajr", "jamaat")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "dhuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
    }
