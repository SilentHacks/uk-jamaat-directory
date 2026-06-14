from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
    ExtractContext,
    ExtractorResult,
    BaseMosqueWebsiteExtractor,
    ExtractorWarning,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    _TabularTimetableMixin,
)
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time


class Extractor(BaseMosqueWebsiteExtractor):
    key = "former_baitul_aman_mosque_and_cultural_centre_b8e10753"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("baitulaman.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://baitulaman.org/prayer-times/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        
        table = html_helpers.find_table(artifact.text(), header_keywords=("fajr", "zuhr"))
        if not table:
            return ExtractorResult(
                rows=[],
                warnings=[ExtractorWarning(code="no_table", message="no prayer table found", target_label="timetable")],
                no_schedule_reason="timetable table not found",
            )
        
        # Dynamically find columns: find first row with "jama'at" or "iqama"
        header = [cell.lower().strip() for cell in table.header]
        
        # Find prayer columns by looking for "jama'at" after prayer names
        prayer_cols = {}
        for idx, cell in enumerate(header):
            if "jama" in cell or "iqama" in cell:
                if "fajr" in " ".join(header[:idx]):
                    prayer_cols[Prayer.FAJR] = idx
                elif "zuhr" in " ".join(header[:idx]):
                    prayer_cols[Prayer.DHUHR] = idx
                elif "asr" in " ".join(header[:idx]):
                    prayer_cols[Prayer.ASR] = idx
                elif "maghrib" in " ".join(header[:idx]):
                    prayer_cols[Prayer.MAGHRIB] = idx
                elif "isha" in " ".join(header[:idx]):
                    prayer_cols[Prayer.ISHA] = idx
        
        # Fall back to indices if dynamic search didn't work
        if not prayer_cols:
            prayer_cols = {
                Prayer.FAJR: 2,
                Prayer.DHUHR: 5,
                Prayer.ASR: 7,
                Prayer.MAGHRIB: 9,
                Prayer.ISHA: 11,
            }
        
        # Extract rows: date is column 0, prayers in dedicated columns
        rows = []
        seen_keys = set()
        for row_num, row_data in enumerate(table.body(), start=1):
            cells = [cell.strip() for cell in row_data]
            if not cells or not cells[0].isdigit():
                continue
            
            day = int(cells[0])
            from datetime import datetime
            today = datetime.now()
            month = today.month
            year = today.year
            
            try:
                row_date = date(year, month, day)
            except ValueError:
                continue
            
            for prayer, col_idx in prayer_cols.items():
                if col_idx >= len(cells):
                    continue
                time_str = cells[col_idx].strip()
                if not time_str:
                    continue
                
                # Skip duplicate entries (same date+prayer combo)
                key = (row_date, prayer)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                
                jamaat = coerce_time(time_str, prayer=prayer.value)
                if jamaat:
                    from uk_jamaat_directory.ingest.extract.repo_extractors.contract import ExtractorRow
                    rows.append(
                        ExtractorRow(
                            date=row_date,
                            prayer=prayer,
                            jamaat_time=jamaat,
                            start_time=None,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=" | ".join(cells),
                                selector=f"table row {row_num}",
                            ),
                        )
                    )
        
        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no extractable rows")
        
        return ExtractorResult(rows=rows)
