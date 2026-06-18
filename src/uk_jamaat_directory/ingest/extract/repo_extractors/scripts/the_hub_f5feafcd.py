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
    key = "the_hub_f5feafcd"
    version = "2026.06.18.1"
    source_match = SourceMatch(domains=("deencentral.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://deencentral.org/prayer-times/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("fajr",)
    date_column = 0
    # Two-row header; data rows are Begins/Jamaat pairs:
    # 0=Date,1=Day,2=FajrBegins,3=FajrJamaat,4=Sunrise,5=ZuhrBegins,6=ZuhrJamaat,
    # 7=AsrBegins,8=AsrJamaat,9=MaghBegins,10=MaghJamaat,11=IshaBegins,12=IshaJamaat
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 8,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }
