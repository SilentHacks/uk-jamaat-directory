from datetime import date, datetime

from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
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
from uk_jamaat_directory.domain import Prayer


class Extractor(BaseMosqueWebsiteExtractor):
    key = "leeds_islamic_centre_415fc02e"
    version = "2026.06.13.2"
    source_match = SourceMatch(domains=("leedsic.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self):
        month_names = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ]
        now = datetime.now()
        
        targets = []
        for offset in [0, 1]:  # Current month and next month
            m = now.month + offset
            y = now.year
            if m > 12:
                m -= 12
                y += 1
            month_pad = f"{m:02d}"
            month_name = month_names[m - 1]
            url = f"https://leedsic.com/prayers/{month_pad}.{month_name}.html"
            targets.append(
                TargetSpec(
                    label=f"timetable_{month_pad}",
                    url=url,
                    kind=TargetKind.HTML,
                )
            )
        
        self.targets = tuple(targets)

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        extracted_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        prev_times = {}
        now = datetime.now()
        
        # Process both current and next month
        for offset in [0, 1]:
            m = now.month + offset
            y = now.year
            if m > 12:
                m -= 12
                y += 1
            
            target_label = f"timetable_{m:02d}"
            body = ctx.artifact(target_label)
            if not body.body:
                continue
            
            html = body.text()
            tables = extract_tables(html)
            
            if not tables or len(tables) < 3:
                continue
            
            table = tables[2]
            rows = list(table.body())
            
            if not rows:
                continue
            
            for row_index, row in enumerate(rows):
                cells = list(row)
                if not cells or len(cells) < 1:
                    continue
                
                if row_index < 6:
                    continue
                
                first_cell = cells[0].strip()
                
                try:
                    day = int(first_cell)
                    if day < 1 or day > 31:
                        continue
                except ValueError:
                    continue
                
                if len(cells) < 11:
                    continue
                
                try:
                    prayer_date = date(y, m, day)
                except ValueError:
                    continue
                
                jamaat_prayers = [
                    (Prayer.FAJR, 7),
                    (Prayer.DHUHR, 8),
                    (Prayer.ASR, 9),
                    (Prayer.ISHA, 10),
                ]
                
                for prayer, col_idx in jamaat_prayers:
                    time_str = cells[col_idx].strip() if col_idx < len(cells) else ""
                    
                    if not time_str:
                        continue
                    
                    jamaat_time = None
                    
                    if time_str == '"':
                        if prayer in prev_times:
                            jamaat_time = prev_times[prayer]
                        else:
                            continue
                    else:
                        jamaat_time = coerce_time(time_str, prayer=prayer.value)
                        if jamaat_time:
                            prev_times[prayer] = jamaat_time
                        else:
                            continue
                    
                    if not jamaat_time:
                        continue
                    
                    evidence = ctx.evidence(
                        target_label=target_label,
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=time_str,
                        selector=f"table tbody tr:nth-child({row_index + 1})",
                    )
                    
                    extracted_rows.append(
                        ExtractorRow(
                            date=prayer_date,
                            prayer=prayer,
                            jamaat_time=jamaat_time,
                            timezone=ctx.timezone,
                            evidence=evidence,
                        )
                    )
        
        if not extracted_rows:
            warnings.append(
                ExtractorWarning(
                    code="no_extractable_rows",
                    message="no rows were extractable from tables",
                    target_label="timetable_06",
                )
            )
        
        return ExtractorResult(
            rows=extracted_rows,
            warnings=warnings,
        )
