"""Extractor for Zakariyya Jaam'e Masjid (Bolton)."""

from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.html import Table
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    ExtractorWarning,
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
    key = "zakariyya_jaam_e_masjid_9805cedb"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("zakariyyamasjid.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://zakariyyamasjid.co.uk/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("prayer", "begins")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 3,
        Prayer.ASR: 3,
        Prayer.MAGHRIB: 3,
        Prayer.ISHA: 3,
    }
    start_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 2,
        Prayer.ASR: 2,
        Prayer.MAGHRIB: 2,
        Prayer.ISHA: 2,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        table = html_helpers.find_table(artifact.text(), header_keywords=list(self.table_keywords))
        if table is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message=f"no table matching {self.table_keywords}",
                        target_label=self.target_label,
                    )
                ],
                no_schedule_reason="timetable table not found",
            )
        # Inject date column with today's date
        today = datetime.now().date()
        body_with_date = [[str(today)] + row for row in table.body()]
        table_with_date = Table([["date"] + table.header] + body_with_date)
        
        # Parse rows manually to match prayer names with times
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        
        prayer_map = {
            "fajr": Prayer.FAJR,
            "dhuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }
        
        for row_num, row in enumerate(table_with_date.body(), start=1):
            prayer_name = row[1].lower() if len(row) > 1 else ""
            prayer = prayer_map.get(prayer_name)
            if not prayer:
                continue
            
            jamaat_raw = row[3] if len(row) > 3 else ""
            if not jamaat_raw:
                continue
            
            jamaat = coerce_time(jamaat_raw, prayer=prayer.value)
            if jamaat is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{today} {prayer.value}: {jamaat_raw!r}",
                        target_label=self.target_label,
                    )
                )
                continue
            
            start_raw = row[2] if len(row) > 2 else ""
            start = coerce_time(start_raw, prayer=prayer.value) if start_raw else None
            
            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    start_time=start,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label=self.target_label,
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join(row),
                        selector=f"table row {row_num}",
                    ),
                )
            )
        
        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=rows, warnings=warnings)
