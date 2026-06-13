from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import relative, times
from uk_jamaat_directory.ingest.extract.helpers.html import find_table
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
    PLAUSIBLE_WINDOWS,
)


class Extractor(TableTimetableExtractor):
    key = "chadwell_heath_muslim_centre_8e1dfec0"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("chadwellheathmuslimcentre.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.chadwellheathmuslimcentre.co.uk/?page_id=392",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = 1  # Index-based: "Date" is column 1
    prayer_columns = {
        Prayer.FAJR: 4,      # Fajr adhan column
        Prayer.DHUHR: 6,     # Dhuhr jamaat
        Prayer.ASR: 7,       # Asr jamaat
        Prayer.MAGHRIB: 9,   # Maghrib adhan column
        Prayer.ISHA: 10,     # Isha jamaat
    }

    def clean_cell(self, value: str) -> str:
        """Clean header and cell values (strip whitespace)."""
        return value.strip()

    def accept_row(self, row: list[str], row_date: date) -> bool:
        """Accept all rows with valid dates in Ramadan 1447 (Feb-Mar 2026)."""
        return row_date.year == 2026 and 2 <= row_date.month <= 3

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """Override to apply prayer-specific time transformations."""
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        
        table = find_table(artifact.text(), header_keywords=list(self.table_keywords))
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
        
        header = [self.clean_cell(cell) for cell in table.header]
        warnings: list[ExtractorWarning] = []
        
        date_idx = self._column_index(header, self.date_column)
        if date_idx is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_date_column",
                        message=f"date column {self.date_column!r} not found",
                        target_label=self.target_label,
                    )
                ],
                no_schedule_reason="date column not found",
            )
        
        prayer_idx: dict[Prayer, int] = {}
        for prayer, spec in self.prayer_columns.items():
            idx = self._column_index(header, spec)
            if idx is None:
                idx = spec if isinstance(spec, int) else None
            if idx is None:
                warnings.append(
                    ExtractorWarning(
                        code="missing_prayer_column",
                        message=f"column {spec!r} for {prayer.value} not found",
                        target_label=self.target_label,
                    )
                )
            else:
                prayer_idx[prayer] = idx
        
        if not prayer_idx:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no prayer columns found",
            )
        
        body = [[self.clean_cell(cell) for cell in row] for row in table.body()]
        
        year = self.current_year(ctx)
        month = self.current_month(ctx)
        rows: list[ExtractorRow] = []
        
        for row_number, row in enumerate(body, start=1):
            if date_idx >= len(row):
                continue
            row_date = self.parse_date_cell(row[date_idx], year=year, month=month)
            if row_date is None or not self.accept_row(row, row_date):
                continue
            
            for prayer, idx in prayer_idx.items():
                raw = row[idx] if idx < len(row) else ""
                if not raw:
                    continue
                
                # Parse the raw time first
                adhan = times.coerce_time(raw, prayer=prayer.value)
                if adhan is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value} (raw): {raw!r}",
                            target_label=self.target_label,
                        )
                    )
                    continue
                
                # Apply prayer-specific transformations
                if prayer == Prayer.FAJR:
                    # Fajr column contains adhan; jamaat = adhan + 15 min
                    jamaat = relative.jamaat_after_start(adhan, minutes=15)
                elif prayer == Prayer.MAGHRIB:
                    # Maghrib column contains adhan; jamaat = adhan + 15 min
                    jamaat = relative.jamaat_after_start(adhan, minutes=15)
                else:
                    # Dhuhr, Asr, Isha columns already contain jamaat times
                    jamaat = adhan
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {jamaat_str!r}",
                            target_label=self.target_label,
                        )
                    )
                    continue
                
                window = PLAUSIBLE_WINDOWS.get(prayer.value)
                if window and not (window[0] <= jamaat <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{row_date} {prayer.value}: {jamaat_str!r} outside plausible window",
                            target_label=self.target_label,
                        )
                    )
                    continue
                
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        start_time=None,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label=self.target_label,
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(row),
                            selector=f"table row {row_number}",
                        ),
                    )
                )
        
        return ExtractorResult(rows=rows, warnings=warnings)
