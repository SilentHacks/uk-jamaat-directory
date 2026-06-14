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
    key = "aylesbury_vale_islamic_centre_5870fad7"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("aylesburyislamiccentre.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://aylesburyislamiccentre.com/prayer-timetable/",
            kind=TargetKind.HTML,
        ),
    )

    table_keywords = ("date", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "dhuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html_text = artifact.text()
        tables = html_helpers.extract_tables(html_text)

        # Find table with prayer times (sky-monthly-table)
        timetable = None
        for t in tables:
            found_date = False
            found_fajr = False
            for row in t.rows:
                row_lower = " ".join(c.lower() for c in row)
                if "date" in row_lower or "mon" in row_lower:
                    found_date = True
                if "fajr" in row_lower:
                    found_fajr = True
            if found_date and found_fajr:
                timetable = t
                break

        if timetable is None:
            return ExtractorResult(rows=[], no_schedule_reason="prayer times table not found")

        # Extract all data-date values from HTML for date mapping
        date_attrs = re.findall(r'data-date="(\d{4})-(\d{2})-(\d{2})"', html_text)
        date_map = {}
        for i, (year, month, day) in enumerate(date_attrs):
            date_map[i] = datetime(int(year), int(month), int(day)).date()

        # Map prayer column names to indices
        prayer_map = {
            "fajr": Prayer.FAJR,
            "dhuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        # Find header row and prayer column indices
        header_row_idx = None
        col_map = {}
        for i, row in enumerate(timetable.rows):
            r_lower = [c.lower() for c in row]
            if any(p in r_lower for p in prayer_map.keys()):
                header_row_idx = i
                for prayer_name in prayer_map.keys():
                    if prayer_name in r_lower:
                        col_map[prayer_map[prayer_name]] = r_lower.index(prayer_name)
                break

        if header_row_idx is None or not col_map:
            return ExtractorResult(rows=[], no_schedule_reason="prayer column headers not found")

        rows_out: list[ExtractorRow] = []
        row_idx = 0

        # Process prayer rows (skip header)
        for r in timetable.rows[header_row_idx + 1 :]:
            if not r or len(r) < 2:
                continue

            # Extract date from first column (e.g., "Mon 1", "Tue 2")
            date_text = r[0].lower().strip()
            if not date_text or any(skip in date_text for skip in ["sunrise", "loading"]):
                continue

            # Get date from date_map
            if row_idx not in date_map:
                row_idx += 1
                continue
            row_date = date_map[row_idx]
            row_idx += 1

            # Extract jamaat times for each prayer
            for prayer, col_idx in col_map.items():
                if col_idx >= len(r):
                    continue

                cell_text = r[col_idx].strip()
                if not cell_text:
                    continue

                # Extract iqamah time: look for pattern like "Iqm 3:45 AM" or "Iqamah 3:45 AM"
                jamaat_match = re.search(
                    r"iq[a]?m(?:ah)?\s*(\d{1,2}:\d{2}\s*(?:am|pm))", cell_text, re.I
                )
                if jamaat_match:
                    jamaat_str = jamaat_match.group(1)
                    jamaat = coerce_time(jamaat_str, prayer=prayer.value)
                    if jamaat:
                        rows_out.append(
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
                                    raw_text=cell_text,
                                    selector=f"prayer times table row, {prayer.value} column",
                                ),
                            )
                        )

        if not rows_out:
            return ExtractorResult(rows=[], no_schedule_reason="no extractable rows")

        return ExtractorResult(rows=rows_out, warnings=[])
