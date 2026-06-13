from datetime import datetime, date

from uk_jamaat_directory.domain import Prayer
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
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time


class Extractor(BaseMosqueWebsiteExtractor):
    key = "medina_mosque___islamic_centre_e456fe79"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("themadinamosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    target_label = "timetable"
    targets = (
        TargetSpec(
            label="timetable",
            url="https://themadinamosque.com/",
            kind=TargetKind.HTML,
        ),
    )

    PRAYER_MAP = {
        "fajr": Prayer.FAJR,
        "zuhr": Prayer.DHUHR,
        "asr": Prayer.ASR,
        "maghrib": Prayer.MAGHRIB,
        "isha": Prayer.ISHA,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        tables = extract_tables(artifact.text())

        # Find the prayer table (body row 1 has Fajr, etc)
        table = None
        for t in tables:
            if len(t.body()) > 1:
                data_row = t.body()[1]
                if len(data_row) >= 3:
                    prayer_cell = data_row[0].lower()
                    if any(p in prayer_cell for p in ['fajr', 'zuhr', 'asr', 'maghrib', 'isha']):
                        table = t
                        break

        if table is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no prayer table found",
                        target_label=self.target_label,
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        rows = []
        today = datetime.now().date()

        # Skip header row (body[0]), process data rows
        for i, row in enumerate(table.body()[1:], start=1):
            if len(row) < 3:
                continue

            prayer_name = row[0].strip().lower()
            jamaat_time_str = row[2].strip()

            # Map prayer name to Prayer enum
            prayer = self.PRAYER_MAP.get(prayer_name)
            if not prayer:
                continue

            # Parse time
            jamaat_time = coerce_time(jamaat_time_str)
            if not jamaat_time:
                continue

            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=jamaat_time,
                    evidence=ctx.evidence(
                        target_label=self.target_label,
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join(row),
                        selector=f"table row {i}",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no extractable rows",
            )

        return ExtractorResult(rows=rows)
