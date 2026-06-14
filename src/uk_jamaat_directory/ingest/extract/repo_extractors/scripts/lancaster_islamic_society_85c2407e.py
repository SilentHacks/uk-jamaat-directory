from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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


def _parse_csv_line(line: str) -> list[str]:
    """Parse a CSV line with quoted fields."""
    fields = []
    current = []
    in_quotes = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ',' and not in_quotes:
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    fields.append("".join(current))
    return fields


class Extractor(BaseMosqueWebsiteExtractor):
    key = "lancaster_islamic_society_85c2407e"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("lancasterisoc.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://lancasterisoc.org/times/prayertime.php",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="empty_artifact",
                        message="timetable artifact is empty",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="artifact was empty",
            )

        text = artifact.text()
        lines = text.strip().split("\n")
        if not lines:
            return ExtractorResult(
                rows=[],
                warnings=[],
                no_schedule_reason="no data in artifact",
            )

        # Parse header
        header = [h.strip().strip('"') for h in _parse_csv_line(lines[0])]
        
        # Find column indices
        col_map = {h: i for i, h in enumerate(header)}
        date_idx = col_map.get("date")
        iqamah_cols = {
            Prayer.FAJR: col_map.get("fajr_iqamah"),
            Prayer.DHUHR: col_map.get("dhuhr_iqamah"),
            Prayer.ASR: col_map.get("asr_iqamah"),
            Prayer.MAGHRIB: col_map.get("maghrib_iqamah"),
            Prayer.ISHA: col_map.get("isha_iqamah"),
        }

        if date_idx is None:
            return ExtractorResult(
                rows=[],
                warnings=[],
                no_schedule_reason="date column not found",
            )

        rows = []
        year = datetime.now().year

        for line in lines[1:]:
            if not line.strip():
                continue

            fields = [f.strip().strip('"') for f in _parse_csv_line(line)]
            
            if date_idx >= len(fields):
                continue

            date_str = fields[date_idx]
            if not date_str:
                continue

            try:
                parsed_date = parse_date_flexible(date_str, default_year=year)
            except Exception:
                continue

            for prayer, col_idx in iqamah_cols.items():
                if col_idx is None or col_idx >= len(fields):
                    continue

                time_str = fields[col_idx].strip()
                if not time_str:
                    continue
                
                # Remove seconds if present (HH:MM:SS -> HH:MM)
                if len(time_str) > 5 and time_str[5] == ':':
                    time_str = time_str[:5]
                
                try:
                    jamaat_time = coerce_time(time_str, prayer=prayer.value)
                    if not jamaat_time:
                        continue
                    
                    # Check plausible window
                    window = PLAUSIBLE_WINDOWS.get(prayer.value)
                    if window and not (window[0] <= jamaat_time <= window[1]):
                        continue
                    
                    rows.append(
                        ExtractorRow(
                            date=parsed_date,
                            prayer=prayer,
                            jamaat_time=jamaat_time,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"{prayer.value}={time_str}",
                            ),
                        )
                    )
                except Exception:
                    pass

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=[],
                no_schedule_reason="no jamaat times found",
            )

        return ExtractorResult(rows=rows, warnings=[])
