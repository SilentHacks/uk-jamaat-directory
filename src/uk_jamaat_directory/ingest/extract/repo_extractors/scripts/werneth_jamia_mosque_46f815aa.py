import json
import re
from datetime import datetime
from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time


class Extractor(BaseMosqueWebsiteExtractor):
    key = "werneth_jamia_mosque_46f815aa"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("wernethjamiamasjid.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://wernethjamiamasjid.org.uk/prayer-timetable/",
            kind=TargetKind.HTML,
        ),
    )
    
    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """
        Extract jamaat times from embedded JS variable.
        The website provides full-year cycling times with intelligent year handling.
        """
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        
        html_content = artifact.text()
        rows = []
        
        # Parse the JS variable that contains the jamaat times
        match = re.search(r'var\s+salah_conf\s*=\s*(\{.*?\});', html_content, re.DOTALL)
        if not match:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="awaiting OCR"
            )
        
        try:
            json_str = match.group(1)
            data = json.loads(json_str)
        except (json.JSONDecodeError, ValueError, AttributeError):
            return ExtractorResult(
                rows=[],
                no_schedule_reason="awaiting OCR"
            )
        
        if not isinstance(data, dict) or 'jamatTime' not in data:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="awaiting OCR"
            )
        
        jamat_data = data.get('jamatTime', [])
        now = datetime.now()
        current_year = now.year
        prayer_map = {
            'Fajr': Prayer.FAJR,
            'Dhuhr': Prayer.DHUHR,
            'Asr': Prayer.ASR,
            'Maghrib': Prayer.MAGHRIB,
            'Isha': Prayer.ISHA,
        }
        
        for entry in jamat_data:
            date_str = entry.get('Date')
            if not date_str:
                continue
            
            # Parse "Jan-01" format with intelligent year handling
            try:
                # Try to parse with current year
                parsed = datetime.strptime(f"{date_str}-{current_year}", "%b-%d-%Y")
                date_obj = parsed.date()
                
                # For full-year timetables, adjust year if date is too far away
                # Prefer dates within the next 3 months, or if all are too old, use next year
                days_ahead = (parsed - now).days
                days_behind = (now - parsed).days
                
                # If this date is more than 3 months behind, it's probably from next year's cycle
                if days_behind > 90 and days_ahead + 365 <= 90:
                    parsed = datetime.strptime(f"{date_str}-{current_year + 1}", "%b-%d-%Y")
                    date_obj = parsed.date()
                # If this date is more than 3 months ahead, it's probably from last year's cycle
                elif days_ahead > 90 and days_behind + 365 <= 90:
                    parsed = datetime.strptime(f"{date_str}-{current_year - 1}", "%b-%d-%Y")
                    date_obj = parsed.date()
                    
            except ValueError:
                continue
            
            # Create one row per prayer
            for prayer_key, prayer in prayer_map.items():
                time_str = entry.get(prayer_key, '').strip()
                if not time_str:
                    continue
                
                try:
                    jamaat_time = coerce_time(time_str, prayer=prayer.value)
                    if jamaat_time:
                        row = ExtractorRow(
                            date=date_obj,
                            prayer=prayer,
                            jamaat_time=jamaat_time,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(target_label="timetable"),
                        )
                        rows.append(row)
                except (ValueError, TypeError):
                    pass
        
        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="awaiting OCR"
            )
        
        return ExtractorResult(rows=rows)
