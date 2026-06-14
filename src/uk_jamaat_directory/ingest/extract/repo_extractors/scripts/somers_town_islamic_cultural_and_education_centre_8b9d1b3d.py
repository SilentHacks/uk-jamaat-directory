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
    key = "somers_town_islamic_cultural_and_education_centre_8b9d1b3d"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("somerstownmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://somerstownmosque.com/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("prayer", "begins")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 2,
        Prayer.ASR: 2,
        Prayer.MAGHRIB: 2,
        Prayer.ISHA: 2,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        tables = html_helpers.extract_tables(artifact.text())

        # Find table with "Prayer" and "Begins" headers
        timetable = None
        for t in tables:
            has_prayer = False
            has_begins = False
            for row in t.rows:
                row_lower = " ".join(c.lower() for c in row)
                if "prayer" in row_lower:
                    has_prayer = True
                if "begins" in row_lower:
                    has_begins = True
            if has_prayer and has_begins:
                timetable = t
                break

        if timetable is None:
            return ExtractorResult(rows=[], no_schedule_reason="prayer times table not found")

        # Find header row with "Prayer" and "Begins"
        header_idx = None
        prayer_col = begins_col = jamaat_col = None
        for i, row in enumerate(timetable.rows):
            r_lower = [c.lower() for c in row]
            if "prayer" in r_lower and "begins" in r_lower:
                header_idx = i
                prayer_col = r_lower.index("prayer")
                begins_col = r_lower.index("begins")
                # Jamaat is typically the next column after Begins
                jamaat_col = begins_col + 1 if begins_col + 1 < len(row) else None
                break

        if header_idx is None or prayer_col is None or begins_col is None:
            return ExtractorResult(rows=[], no_schedule_reason="prayer times header not found")

        # Extract date from first row (contains "June 13, 2026" or similar)
        row_date = datetime.now().date()
        if timetable.rows and len(timetable.rows) > 0:
            header_text = " ".join(timetable.rows[0])
            try:
                from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible

                row_date = parse_date_flexible(header_text, default_year=datetime.now().year)
            except:
                pass

        prayer_map = {
            "fajr": Prayer.FAJR,
            "zuhr": Prayer.DHUHR,
            "zohr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        rows_out: list[ExtractorRow] = []

        # Process prayer rows
        for r in timetable.rows[header_idx + 1 :]:
            if len(r) <= prayer_col:
                continue

            prayer_text = r[prayer_col].lower().strip()
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

            # Extract jamaat time (from jamaat column if available)
            jamaat_raw = ""
            if jamaat_col is not None and jamaat_col < len(r):
                jamaat_raw = r[jamaat_col]
            elif begins_col + 1 < len(r):
                jamaat_raw = r[begins_col + 1]

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
