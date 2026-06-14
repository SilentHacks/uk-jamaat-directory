from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy, RunFrequency, SourceMatch, TargetKind, TargetSpec,
    ExtractContext, ExtractorResult, ExtractorWarning, ExtractorRow,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    BaseMosqueWebsiteExtractor,
)
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time, PLAUSIBLE_WINDOWS
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible


class Extractor(BaseMosqueWebsiteExtractor):
    key = "newmarket_islamic_cultural_centre_ddf80948"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("newmarketmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://newmarketmosque.com/",
            kind=TargetKind.HTML,
        ),
    )
    target_label = "timetable"

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        
        tables = html_helpers.extract_tables(artifact.text())
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[ExtractorWarning(code="no_table", message="no tables found", target_label=self.target_label)],
                no_schedule_reason="no tables found",
            )
        
        t = tables[0]
        if len(t.rows) <= 1 or not html_helpers.header_matches(t.rows[1], ("prayer", "begins")):
            return ExtractorResult(
                rows=[],
                warnings=[ExtractorWarning(code="no_table", message="no prayer/begins header found", target_label=self.target_label)],
                no_schedule_reason="timetable table not found",
            )
        
        # Row 1 is header: ['Prayer', 'Begins', 'Jamaat']
        # Rows 2+ are prayers with [Prayer_Name, Start_Time, Jamaat_Time]
        today = datetime.now().date()
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        
        prayer_map = {
            "fajr": Prayer.FAJR,
            "zuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }
        
        for row_number, row in enumerate(t.rows[2:], start=1):
            if len(row) < 3:
                continue
            
            prayer_name = row[0].lower().strip()
            if prayer_name not in prayer_map:
                continue
            
            prayer = prayer_map[prayer_name]
            jamaat_str = row[2].strip()
            start_str = row[1].strip()
            
            if not jamaat_str:
                continue
            
            jamaat = coerce_time(jamaat_str, prayer=prayer.value)
            if jamaat is None:
                warnings.append(ExtractorWarning(
                    code="unparseable_time",
                    message=f"{today} {prayer.value}: {jamaat_str!r}",
                    target_label=self.target_label,
                ))
                continue
            
            window = PLAUSIBLE_WINDOWS.get(prayer.value)
            if window and not (window[0] <= jamaat <= window[1]):
                warnings.append(ExtractorWarning(
                    code="implausible_time",
                    message=f"{today} {prayer.value}: {jamaat_str!r} outside plausible window",
                    target_label=self.target_label,
                ))
                continue
            
            start = None
            if start_str:
                start = coerce_time(start_str, prayer=prayer.value)
            
            rows.append(ExtractorRow(
                date=today,
                prayer=prayer,
                jamaat_time=jamaat,
                start_time=start,
                timezone=ctx.timezone,
                evidence=ctx.evidence(
                    target_label=self.target_label,
                    extractor_key=self.key,
                    extractor_version=self.version,
                    raw_text=f"{today} {prayer.value}: {jamaat_str}",
                    selector=f"row={row_number} col=jamaat",
                ),
            ))
        
        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )
        
        return ExtractorResult(rows=rows, warnings=warnings)
