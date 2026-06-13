import re
from datetime import datetime, date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import times as time_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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


class Extractor(BaseMosqueWebsiteExtractor):
    key = "masjid_as_sunnah_8fffb9da"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("albaseerah.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://albaseerah.com/monthly-prayer-timetable/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    target_label = "timetable"

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        
        html = artifact.text()
        
        # Parse CSS Grid layout with grid-* classes
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        
        # Extract grid items: each row has grid-date, grid-day, grid-fajr, etc.
        grid_dates = re.findall(r'<div[^>]*class="grid-date"[^>]*>([^<]+)<', html)
        grid_fajrs = re.findall(r'<div[^>]*class="grid-fajr"[^>]*>([^<]+)<', html)
        grid_duhrs = re.findall(r'<div[^>]*class="grid-duhr"[^>]*>([^<]+)<', html)
        grid_asrs = re.findall(r'<div[^>]*class="grid-asr"[^>]*>([^<]+)<', html)
        grid_maghribs = re.findall(r'<div[^>]*class="grid-maghrib"[^>]*>([^<]+)<', html)
        grid_ishaas = re.findall(r'<div[^>]*class="grid-ishaa"[^>]*>([^<]+)<', html)
        grid_jumaahs = re.findall(r'<div[^>]*class="grid-jummah"[^>]*>([^<]+)<', html)
        
        if not grid_dates:
            return ExtractorResult(rows=[], no_schedule_reason="no date grid items found")
        
        # Extract month/year from header
        month_match = re.search(r'<div[^>]*id="grid-month"[^>]*>([^<]+)<', html)
        month_str = month_match.group(1).strip() if month_match else ""
        
        year = datetime.now().year
        month = datetime.now().month
        
        # Map month names
        month_names = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12,
        }
        for name, num in month_names.items():
            if name in month_str.lower():
                month = num
                break
        
        # Process each date row
        for i, date_str in enumerate(grid_dates):
            date_str = date_str.strip()
            if not date_str or date_str == "Date":
                continue
            
            # Parse date
            try:
                parsed = parse_date_flexible(date_str, default_year=year)
                if parsed is None:
                    # Try day-only format
                    day_match = re.match(r'^(\d+)', date_str)
                    if day_match:
                        day = int(day_match.group(1))
                        parsed = date(year, month, day)
                    else:
                        continue
            except:
                continue
            
            row_date = parsed
            
            # Extract jamaat times for this row
            prayer_times = {
                Prayer.FAJR: grid_fajrs[i].strip() if i < len(grid_fajrs) else "",
                Prayer.DHUHR: grid_duhrs[i].strip() if i < len(grid_duhrs) else "",
                Prayer.ASR: grid_asrs[i].strip() if i < len(grid_asrs) else "",
                Prayer.MAGHRIB: grid_maghribs[i].strip() if i < len(grid_maghribs) else "",
                Prayer.ISHA: grid_ishaas[i].strip() if i < len(grid_ishaas) else "",
                Prayer.JUMUAH: grid_jumaahs[i].strip() if i < len(grid_jumaahs) else "",
            }
            
            for prayer, raw_time in prayer_times.items():
                if not raw_time or raw_time.lower() in ("fajr", "dhuhr", "asr", "maghrib", "isha", "jumuah"):
                    continue
                
                # Parse time
                jamaat = time_helpers.coerce_time(raw_time, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {raw_time!r}",
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
                            raw_text=raw_time,
                            selector=f"grid item row {i}",
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
