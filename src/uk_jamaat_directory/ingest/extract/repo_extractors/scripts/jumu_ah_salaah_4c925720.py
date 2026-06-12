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
    key = "jumu_ah_salaah_4c925720"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("becktonislamicassociation.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://becktonislamicassociation.org.uk/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("date", "day", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 8,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }

    def accept_row(self, row, row_date):
        if not row or len(row) < 13:
            return False
        return row_date is not None

    def extract(self, ctx):
        res = super().extract(ctx)
        if not res or not res.rows:
            return res
        fixed_rows = []
        for r in res.rows:
            if r.prayer == Prayer.DHUHR and r.date.weekday() == 4:
                r = r.model_copy(update={"prayer": Prayer.JUMUAH})
            fixed_rows.append(r)
        return res.model_copy(update={"rows": fixed_rows})
