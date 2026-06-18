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
    """Faizan-e-Islam Centre — daily-prayer-time-for-mosques monthly table.

    Two-row header (prayer-name row then Begins/Jamaat sub-row). The previous
    custom parser matched prayer names against the short 6-cell name row which
    misaligned with the 13-cell data rows; the Jamaat (jamaat) columns sit at
    fixed positions 3/6/8/10/12.
    """

    key = "faizan_e_islam_centre_c7d7d4ad"
    version = "2026.06.18.1"
    source_match = SourceMatch(domains=("faizaneislam.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://faizaneislam.com/prayer-times/prayer-times-london/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("fajr",)
    date_column = 0
    # 0=Date,1=Day,2=FajrBegins,3=FajrJamaat,4=Sunrise,5=ZuhrBegins,6=ZuhrJamaat,
    # 7=AsrBegins,8=AsrJamaat,9=MaghBegins,10=MaghJamaat,11=IshaBegins,12=IshaJamaat
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 8,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }
