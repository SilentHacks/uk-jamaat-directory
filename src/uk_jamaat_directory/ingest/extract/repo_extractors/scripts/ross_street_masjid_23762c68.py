"""
Ross Street Masjid prayer times extractor.

Target: https://rossstreetmasjid.org/salat-timings/
Parses daily iqamah times from the Salat Timings page.
"""

from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import find_table
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorEvidence,
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
    key = "ross_street_masjid_23762c68"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("rossstreetmasjid.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://rossstreetmasjid.org/salat-timings/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("namaz", "iqamah")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 2,
        Prayer.ASR: 2,
        Prayer.MAGHRIB: 2,
        Prayer.ISHA: 2,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """Custom extraction matching prayer names to rows dynamically."""
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        table = find_table(artifact.text(), header_keywords=list(self.table_keywords))
        if table is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable table not found",
            )

        prayer_map = {
            "fajr": Prayer.FAJR,
            "zuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "magrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        rows: list[ExtractorRow] = []
        today = date.today()

        for row_data in table.body():
            if len(row_data) < 3:
                continue

            prayer_name = self.clean_cell(row_data[0]).lower()
            if prayer_name not in prayer_map:
                continue

            prayer = prayer_map[prayer_name]
            jamaat_raw = self.clean_cell(row_data[2])

            if not jamaat_raw:
                continue

            jamaat_time = coerce_time(jamaat_raw, prayer=prayer.value)
            if jamaat_time is None:
                continue

            evidence = ExtractorEvidence(
                target_label=self.target_label,
                target_url=artifact.target_url,
                extractor_key=self.key,
                extractor_version=self.version,
            )

            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=jamaat_time,
                    evidence=evidence,
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no valid prayer times found",
            )

        return ExtractorResult(rows=rows)

    def clean_cell(self, value: str) -> str:
        """Clean and normalize cell content."""
        value = value.strip()
        # Remove HTML tags (e.g., <i class="fa fa-sun-o">)
        import re

        value = re.sub(r"<[^>]+>", "", value).strip()
        return value
