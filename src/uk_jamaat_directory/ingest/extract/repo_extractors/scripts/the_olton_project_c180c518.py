from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables, Table
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
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
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time


class Extractor(BaseMosqueWebsiteExtractor):
    key = "the_olton_project_c180c518"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("theoltonproject.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://theoltonproject.com/prayer/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        
        html = artifact.text()
        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no table found in rendered HTML",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no table found",
            )
        
        table = tables[0]
        rows_list = list(table.body())
        
        if len(rows_list) < 2:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no data rows in table",
            )
        
        # Skip the month/prayer header row, use the subheader (Date, Day, Begins, Jamaat, ...) as guide
        # Data starts from row 1 (index 1)
        
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        
        for row_number, row in enumerate(rows_list[1:], start=2):
            if not row or not row[0].strip():
                continue
            
            # Column 0: Date (e.g., "1 June 2026")
            date_text = row[0].strip()
            parsed_date = parse_date_flexible(date_text, default_year=2026)
            if not parsed_date:
                warnings.append(
                    ExtractorWarning(
                        code="bad_date",
                        message=f"row {row_number}: could not parse date '{date_text}'",
                        target_label="timetable",
                    )
                )
                continue
            
            # Extract jamaat times from fixed columns
            # Col 3: Fajr jamaat, Col 6: Zuhr jamaat, Col 8: Asr jamaat, Col 10: Maghrib jamaat, Col 12: Isha jamaat
            prayer_cols = {
                Prayer.FAJR: 3,
                Prayer.DHUHR: 6,
                Prayer.ASR: 8,
                Prayer.MAGHRIB: 10,
                Prayer.ISHA: 12,
            }
            
            for prayer, col_idx in prayer_cols.items():
                if col_idx >= len(row):
                    continue
                time_text = row[col_idx].strip()
                if not time_text:
                    continue
                
                jamaat_time = coerce_time(time_text, prayer=prayer.value)
                if not jamaat_time:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{parsed_date} {prayer.value}: {time_text!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                
                rows.append(
                    ExtractorRow(
                        date=parsed_date,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        start_time=None,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{parsed_date} {prayer.value} {time_text}",
                            selector=f"table tr {row_number} col {col_idx}",
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

