from datetime import date, datetime, time

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time, PLAUSIBLE_WINDOWS
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
    key = "quwwatul_islam_masjid_97d151eb"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("quwwatulislam.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://quwwatulislam.org.uk/prayer-timetable/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        
        if not tables:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="artifact was empty",
            )
        
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []
        
        for table in tables:
            body = table.body()
            
            # Check if first body row contains Prayer, Begins, Iqamah headers
            # (table header row contains the date instead)
            if not body:
                continue
            
            potential_header = [html_helpers.normalize_whitespace(cell).lower() for cell in body[0]]
            if not ("prayer" in str(potential_header) and "begins" in str(potential_header) and "iqamah" in str(potential_header)):
                continue
            
            # Find column indices from the actual header (first body row)
            prayer_col = next((i for i, h in enumerate(potential_header) if "prayer" in h), None)
            begins_col = next((i for i, h in enumerate(potential_header) if "begins" in h), None)
            iqamah_col = next((i for i, h in enumerate(potential_header) if "iqamah" in h), None)
            
            if prayer_col is None or iqamah_col is None:
                continue
            
            # Extract today's date from the page (or use current date)
            today = datetime.now().date()
            
            # Process body rows (starting from row 1, since row 0 is the header)
            for row_index, row in enumerate(body[1:], start=2):
                if prayer_col >= len(row):
                    continue
                
                prayer_name = html_helpers.normalize_whitespace(row[prayer_col]).strip()
                if not prayer_name or prayer_name.lower() == "sunrise":
                    continue
                
                prayer = parse_prayer_label(prayer_name)
                if prayer is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unknown_prayer",
                            message=f"row {row_index}: unknown prayer '{prayer_name}'",
                            target_label="timetable",
                        )
                    )
                    continue
                
                if iqamah_col >= len(row):
                    continue
                
                iqamah_text = html_helpers.normalize_whitespace(row[iqamah_col]).strip()
                if not iqamah_text:
                    continue
                
                jamaat_time = coerce_time(iqamah_text, prayer=prayer.value)
                if jamaat_time is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"row {row_index} ({prayer.value}): {iqamah_text!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                
                # Check plausible window
                window = PLAUSIBLE_WINDOWS.get(prayer.value)
                if window and not (window[0] <= jamaat_time <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"row {row_index} ({prayer.value}): {iqamah_text!r} outside plausible window",
                            target_label="timetable",
                        )
                    )
                    continue
                
                start_time = None
                if begins_col is not None and begins_col < len(row):
                    begins_text = html_helpers.normalize_whitespace(row[begins_col]).strip()
                    if begins_text:
                        start_time = coerce_time(begins_text, prayer=prayer.value)
                
                rows.append(
                    ExtractorRow(
                        date=today,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        start_time=start_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(row),
                            selector=f"table row {row_index}",
                        ),
                    )
                )
            
            if rows:
                break
        
        if not rows:
            reason = "artifact was empty"
            if not warnings:
                warnings.append(
                    ExtractorWarning(
                        code="no_extractable_rows",
                        message="no extractable rows found",
                        target_label="timetable",
                    )
                )
            return ExtractorResult(rows=rows, warnings=warnings, no_schedule_reason=reason)
        
        return ExtractorResult(rows=rows, warnings=warnings)
