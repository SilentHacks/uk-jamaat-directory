from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import Table, extract_tables
from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS, coerce_time
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
    key = "brixton_hill_islamic_centre_dbed119c"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("bhic.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.bhic.org.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.targets[0].label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        tables = extract_tables(artifact.text())
        if not tables:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no tables found",
            )

        target_table = None
        for table in tables:
            body_rows = table.body()
            if len(body_rows) > 4 and len(body_rows[0]) >= 3:
                first_row = body_rows[0]
                if all(
                    any(kw.lower() in cell.lower() for cell in first_row)
                    for kw in ("prayer", "begins")
                ):
                    target_table = Table([first_row] + body_rows[1:])
                    break

        if not target_table:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="prayer timetable not found",
            )

        rows: list[ExtractorRow] = []
        today = datetime.now().date()

        prayer_map = {
            "fajr": Prayer.FAJR,
            "zuhr": Prayer.DHUHR,
            "dhuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        for row_num, row in enumerate(target_table.body(), start=1):
            if len(row) < 3:
                continue

            prayer_name = row[0].strip().lower()
            if prayer_name == "sunrise" or prayer_name not in prayer_map:
                continue

            prayer = prayer_map[prayer_name]
            jamaat_time_str = row[2].strip()

            jamaat = coerce_time(jamaat_time_str, prayer=prayer.value)
            if jamaat is None:
                continue

            window = PLAUSIBLE_WINDOWS.get(prayer.value)
            if window and not (window[0] <= jamaat <= window[1]):
                continue

            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    evidence=ctx.evidence(
                        target_label=self.targets[0].label,
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join(row),
                        selector=f"table row {row_num}",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no extractable rows")

        return ExtractorResult(rows=rows)
