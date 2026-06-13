from datetime import date, datetime, time
import re

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
    BaseMosqueWebsiteExtractor,
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    ExtractorEvidence,
)
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time


class Extractor(BaseMosqueWebsiteExtractor):
    key = "yca_cultural_centre_ea8436cf"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("yca-sandwell.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://yca-sandwell.org.uk/prayer-timetable/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact body was empty")
        html = artifact.text()
        
        # Extract tbody content using regex
        tbody_match = re.search(r'<tbody[^>]*>(.*?)</tbody>', html, re.DOTALL)
        if not tbody_match:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable tbody not found",
            )
        
        tbody_html = tbody_match.group(1)
        
        # Extract rows
        row_pattern = r'<tr[^>]*>(.*?)</tr>'
        rows_data = []
        
        for row_match in re.finditer(row_pattern, tbody_html, re.DOTALL):
            row_html = row_match.group(1)
            # Extract cells
            cell_pattern = r'<td[^>]*>(.*?)</td>'
            cells = []
            for cell_match in re.finditer(cell_pattern, row_html):
                cell_text = cell_match.group(1).strip()
                cells.append(cell_text)
            
            if len(cells) >= 13:
                rows_data.append(cells)
        
        # Column indices for jamaat times
        jamaat_columns = {
            Prayer.FAJR: 3,
            Prayer.DHUHR: 6,
            Prayer.ASR: 8,
            Prayer.MAGHRIB: 10,
            Prayer.ISHA: 12,
        }
        
        rows = []
        for cells in rows_data:
            date_str = cells[0].strip()
            if not date_str:
                continue
            
            try:
                row_date = parse_date_flexible(date_str, default_year=datetime.now().year)
            except Exception:
                continue
            
            for prayer, col_idx in jamaat_columns.items():
                if col_idx < len(cells):
                    time_str = cells[col_idx].strip()
                    if time_str:
                        try:
                            jamaat_t = coerce_time(time_str)
                            rows.append(ExtractorRow(
                                date=row_date,
                                prayer=prayer,
                                jamaat_time=jamaat_t,
                                evidence=ExtractorEvidence(
                                    target_label="timetable",
                                    target_url="https://yca-sandwell.org.uk/prayer-timetable/",
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                ),
                            ))
                        except Exception:
                            pass
        
        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no jamaat times found")
        return ExtractorResult(rows=rows)
