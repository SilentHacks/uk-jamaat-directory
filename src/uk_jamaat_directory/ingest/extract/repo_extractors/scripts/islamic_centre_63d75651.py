import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS, coerce_time
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
    """Extractor for Hamilton Islamic Centre prayer timetable.
    
    The page is JavaScript-rendered (loads prayer times from CSV into HTML table).
    This extractor will work when proper JavaScript rendering is available.
    """
    
    key = "islamic_centre_63d75651"
    version = "2026.06.13.2"
    source_match = SourceMatch(domains=("hamiltonislamiccentre.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://hamiltonislamiccentre.co.uk/html/prayertimes.html",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="artifact empty or not rendered",
            )

        html = artifact.text()
        year = datetime.now().year
        extracted_rows = []
        warnings = []
        
        # Parse table rows when JavaScript has rendered them
        # Table structure: Day, Month, FajrAdhan, FajrIqamah, Shouruq, DhuhrAdhan, DhuhrIqamah,
        #                 AsrAdhan, AsrIqamah, MaghribAdhan, MaghribIqamah, IshaAdhan, IshaIqamah
        cell_pattern = r'<td[^>]*>([^<]*)</td>'
        rows_pattern = r'<tr>((?:<td[^>]*>[^<]*</td>)+)</tr>'
        
        table_rows = re.findall(rows_pattern, html)
        if not table_rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no table rows found",
            )
        
        prayer_cols = {
            Prayer.FAJR: 3,      # FajrIqamah (0-indexed)
            Prayer.DHUHR: 6,     # DhuhrIqamah
            Prayer.ASR: 8,       # AsrIqamah
            Prayer.MAGHRIB: 10,  # MaghribIqamah
            Prayer.ISHA: 12,     # IshaIqamah
        }
        
        for row_html in table_rows[:365]:
            cells = re.findall(cell_pattern, row_html)
            if len(cells) < 13:
                continue
            
            try:
                day = int(cells[0].strip())
                month = int(cells[1].strip())
                row_date = datetime(year, month, day).date()
            except (ValueError, TypeError):
                continue
            
            for prayer, col_idx in prayer_cols.items():
                raw = cells[col_idx].strip()
                if not raw:
                    continue
                
                try:
                    jamaat_time = coerce_time(raw, prayer=prayer.value)
                    if jamaat_time is None:
                        warnings.append(
                            ExtractorWarning(
                                code="time_parse_error",
                                message=f"{row_date} {prayer.value}: {raw!r}",
                                target_label="timetable",
                            )
                        )
                        continue
                    
                    window = PLAUSIBLE_WINDOWS.get(prayer.value)
                    if window and not (window[0] <= jamaat_time <= window[1]):
                        warnings.append(
                            ExtractorWarning(
                                code="implausible_time",
                                message=f"{row_date} {prayer.value}: {raw!r} outside plausible window",
                                target_label="timetable",
                            )
                        )
                        continue
                    
                    evidence = ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=f"{row_date} {prayer.value} jamaat: {raw}",
                    )
                    extracted_rows.append(
                        ExtractorRow(
                            date=row_date,
                            prayer=prayer,
                            jamaat_time=jamaat_time,
                            timezone=ctx.timezone,
                            evidence=evidence,
                        )
                    )
                except Exception as e:
                    warnings.append(
                        ExtractorWarning(
                            code="extraction_error",
                            message=f"{row_date} {prayer.value}: {raw!r} ({e})",
                            target_label="timetable",
                        )
                    )
        
        if not extracted_rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no rows extracted (check if JavaScript rendered the table)",
            )
        
        return ExtractorResult(rows=extracted_rows, warnings=warnings)

