import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
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
    key = "wimbledon_mosque_51474e9f"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("wimbledonmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://wimbledonmosque.org/",
            kind=TargetKind.HTML,
        ),
    )
    
    table_keywords = ("prayer", "jamat")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: "jamat",
        Prayer.DHUHR: "jamat",
        Prayer.ASR: "jamat",
        Prayer.MAGHRIB: "jamat",
        Prayer.ISHA: "jamat",
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        
        tables = html_helpers.extract_tables(artifact.text())
        
        # Find table containing prayer times (check all rows, not just header)
        timetable = None
        for t in tables:
            found_prayer = False
            found_jamat = False
            for row in t.rows:
                row_lower = " ".join(c.lower() for c in row)
                if "prayer" in row_lower:
                    found_prayer = True
                if "jamat" in row_lower:
                    found_jamat = True
            if found_prayer and found_jamat:
                timetable = t
                break
        
        if timetable is None:
            return ExtractorResult(rows=[], no_schedule_reason="prayer times table not found")
        
        # Find "Prayer", "Begins", "Jamat" header row
        header_row_idx = None
        prayer_col = jamat_col = None
        for i, row in enumerate(timetable.rows):
            r_lower = [c.lower() for c in row]
            if "prayer" in r_lower and "jamat" in r_lower:
                header_row_idx = i
                prayer_col = r_lower.index("prayer")
                jamat_col = r_lower.index("jamat")
                break
        
        if header_row_idx is None or prayer_col is None or jamat_col is None:
            return ExtractorResult(rows=[], no_schedule_reason="prayer times header not found")
        
        # Extract date from merged header row (e.g., "13th June 2026")
        row_date = datetime.now().date()
        header_text = " ".join(timetable.rows[0]) if timetable.rows else ""
        date_match = re.search(
            r"(\d{1,2}(?:st|nd|rd|th)?)\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
            header_text,
            re.I
        )
        if date_match:
            try:
                from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
                row_date = parse_date_flexible(header_text, default_year=datetime.now().year)
            except:
                pass
        
        rows_out: list[ExtractorRow] = []
        prayer_map = {
            "fajr": Prayer.FAJR,
            "zuhr": Prayer.DHUHR,
            "zohr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }
        
        # Process prayer rows (skip header row and sunrise row)
        for r in timetable.rows[header_row_idx + 1:]:
            prayer_text = (r[prayer_col] if prayer_col < len(r) else "").lower().strip()
            if not prayer_text or "sunrise" in prayer_text:
                continue
            
            # Map prayer name
            p = None
            for key, pr in prayer_map.items():
                if key in prayer_text:
                    p = pr
                    break
            if p is None:
                continue
            
            # Extract jamaat time
            jamaat_raw = r[jamat_col] if jamat_col < len(r) else ""
            jamaat = coerce_time(jamaat_raw, prayer=p.value)
            if jamaat is None:
                continue
            
            rows_out.append(
                ExtractorRow(
                    date=row_date,
                    prayer=p,
                    jamaat_time=jamaat,
                    start_time=None,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label=self.target_label,
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join(r),
                        selector="prayer times table row",
                    ),
                )
            )
        
        if not rows_out:
            return ExtractorResult(rows=[], no_schedule_reason="no extractable rows")
        
        return ExtractorResult(rows=rows_out, warnings=[])
