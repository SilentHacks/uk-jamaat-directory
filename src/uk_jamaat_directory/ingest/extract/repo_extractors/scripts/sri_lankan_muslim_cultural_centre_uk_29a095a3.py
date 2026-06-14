from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
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


class Extractor(BaseMosqueWebsiteExtractor):
    key = "sri_lankan_muslim_cultural_centre_uk_29a095a3"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("slmcc.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.slmcc.co.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = extract_tables(html)
        
        if not tables:
            return ExtractorResult(
                rows=[], no_schedule_reason="no tables found"
            )

        # Find the table with Prayer/Begins/Iqamah structure
        matching_table = None
        for table in tables:
            body_rows = list(table.body())
            if body_rows and len(body_rows[0]) >= 3:
                first_row = [cell.strip() for cell in body_rows[0]]
                if (
                    first_row[0].lower() == "prayer"
                    and "begin" in first_row[1].lower()
                    and "iqamah" in first_row[2].lower()
                ):
                    matching_table = table
                    break

        if matching_table is None:
            return ExtractorResult(
                rows=[], no_schedule_reason="prayer table not found"
            )

        body_rows = list(matching_table.body())
        if not body_rows:
            return ExtractorResult(
                rows=[], no_schedule_reason="table has no rows"
            )

        # Skip first row (it's the header), use rest as data
        data_rows = body_rows[1:]
        rows: list[ExtractorRow] = []

        prayer_map = {
            "Fajr": Prayer.FAJR,
            "Zuhr": Prayer.DHUHR,
            "Asr": Prayer.ASR,
            "Maghrib": Prayer.MAGHRIB,
            "Isha": Prayer.ISHA,
        }

        # Today's date
        row_date = datetime.now().date()

        for row_number, row_cells in enumerate(data_rows, start=2):
            if len(row_cells) < 3:
                continue

            prayer_name = row_cells[0].strip()
            if prayer_name not in prayer_map:
                continue

            prayer = prayer_map[prayer_name]
            jamaat_str = row_cells[2].strip()  # Iqamah is column 2

            if not jamaat_str:
                continue

            jamaat_time = coerce_time(jamaat_str, prayer=prayer.value)
            if jamaat_time is None:
                continue

            evidence = ctx.evidence(
                target_label="timetable",
                extractor_key=self.key,
                extractor_version=self.version,
                raw_text=" | ".join(cell.strip() for cell in row_cells),
                selector=f"table row {row_number}",
            )

            rows.append(
                ExtractorRow(
                    date=row_date,
                    prayer=prayer,
                    jamaat_time=jamaat_time,
                    start_time=None,
                    timezone=ctx.timezone,
                    evidence=evidence,
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[], no_schedule_reason="no extractable rows"
            )

        return ExtractorResult(rows=rows)
