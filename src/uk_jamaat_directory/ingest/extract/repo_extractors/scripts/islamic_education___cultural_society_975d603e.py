import re
from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
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
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    BaseMosqueWebsiteExtractor,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "islamic_education___cultural_society_975d603e"
    version = "2026.06.13.1"
    target_label = "timetable"
    source_match = SourceMatch(domains=("hayesmuslimcentre.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://hayesmuslimcentre.org.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """Extract prayer times from the daily timetable."""
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html_text = artifact.text()

        # Find all tables
        tables = html_helpers.extract_tables(html_text)
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[],
                no_schedule_reason="no tables found",
            )

        # Extract date from page
        match = re.search(r"([A-Za-z]+)\s+(\d+),\s+(\d{4})", html_text)
        row_date = None
        if match:
            month_name, day_str, year_str = match.groups()
            row_date = parse_date_flexible(
                f"{month_name} {day_str}, {year_str}", default_year=int(year_str)
            )
        if row_date is None:
            row_date = date.today()

        rows = []
        warnings = []

        # Process each table
        for table in tables:
            body = table.body()
            if not body or len(body) < 1:
                continue

            # Check if first body row has "Prayer" keyword - if so, this is the prayer table
            if not any("prayer" in str(cell).lower() for cell in body[0]):
                continue

            # body[0] is header: ['Prayer', 'Begins', 'Iqamah']
            # body[1:] are data rows: ['Fajr', '1:02 am', '3:45 am'], etc.

            for data_row in body[1:]:
                if len(data_row) < 3:
                    continue

                prayer_name = data_row[0].lower().strip()
                begin_time = data_row[1].strip()
                jamaat_time = data_row[2].strip()

                # Map prayer name
                prayer = None
                if "fajr" in prayer_name:
                    prayer = Prayer.FAJR
                elif "zuhr" in prayer_name or "dhuhr" in prayer_name:
                    prayer = Prayer.DHUHR
                elif "asr" in prayer_name:
                    prayer = Prayer.ASR
                elif "maghrib" in prayer_name:
                    prayer = Prayer.MAGHRIB
                elif "isha" in prayer_name:
                    prayer = Prayer.ISHA
                elif "jumu" in prayer_name:
                    prayer = Prayer.DHUHR  # Jumu'ah is Friday Dhuhr
                else:
                    continue  # Skip sunrise and unknown rows

                # Skip if no jamaat time
                if not jamaat_time:
                    continue

                # Parse jamaat time
                jamaat = coerce_time(jamaat_time, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value} jamaat: {jamaat_time!r}",
                            target_label=self.target_label,
                        )
                    )
                    continue

                # Parse start time
                start = None
                if begin_time:
                    start = coerce_time(begin_time, prayer=prayer.value)

                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        start_time=start,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label=self.target_label,
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(data_row),
                            selector=f"table row: {prayer_name}",
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
