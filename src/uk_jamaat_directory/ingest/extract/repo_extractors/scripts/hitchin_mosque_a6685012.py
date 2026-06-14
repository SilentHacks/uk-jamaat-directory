from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import find_table
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
    BaseMosqueWebsiteExtractor,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "hitchin_mosque_a6685012"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("hitchinmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://hitchinmosque.org/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()

        # Try to find the proper timetable (Prayer | Begins | Jamaat)
        table = find_table(html, header_keywords=("prayer", "begins", "jamaat"))
        if not table:
            table = find_table(html, header_keywords=("prayer", "begins"))
        if not table:
            # Try the simpler "Namaz" table
            table = find_table(html, header_keywords=("namaz",))

        if not table:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable table not found",
            )

        rows = []
        today = date.today()
        row_number = 0

        # Find column indices
        header = [cell.lower().strip() for cell in table.header]

        # Find jamaat column (could be "jamaat", "jamah", or last column)
        jamaat_col = None
        for i, h in enumerate(header):
            if "jamaat" in h or "jamah" in h:
                jamaat_col = i
                break
        if jamaat_col is None and len(header) >= 2:
            jamaat_col = len(header) - 1

        # Map prayer names to Prayer enum
        prayer_map = {
            "fajr": Prayer.FAJR,
            "zuhr": Prayer.DHUHR,
            "dhuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "magrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        for row_cells in table.body():
            row_number += 1
            if not row_cells:
                continue

            prayer_name = row_cells[0].strip().lower()

            # Skip non-prayer rows
            if not prayer_name or prayer_name in ("prayer", "namaz", "sunrise"):
                continue

            prayer = prayer_map.get(prayer_name)
            if not prayer:
                continue

            # Extract jamaat time
            if jamaat_col is None or jamaat_col >= len(row_cells):
                continue

            raw_time = row_cells[jamaat_col].strip()
            if not raw_time or raw_time.lower() in ("jamaat", "jamah", "time", "begins"):
                continue

            # Parse time
            jamaat = coerce_time(raw_time, prayer=prayer.value)
            if jamaat is None:
                continue

            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join(row_cells),
                        selector=f"table row {row_number}",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no extractable rows",
            )

        return ExtractorResult(rows=rows)
