from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
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


class Extractor(BaseMosqueWebsiteExtractor):
    key = "masjid_ghousia_176f6475"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("masjidghousia.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidghousia.org/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        tables = extract_tables(artifact.text())
        if not tables:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no tables found",
                warnings=[
                    ExtractorWarning(
                        code="no_table", message="no tables found", target_label="timetable"
                    )
                ],
            )

        target_table = None
        for table in tables:
            if len(table.rows) < 3:
                continue
            header = [cell.lower() for cell in table.rows[1]] if len(table.rows) > 1 else []
            if "prayer" in header and "jamaat" in header:
                target_table = table
                break

        if target_table is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable table not found",
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no table with Prayer/Jamaat headers",
                        target_label="timetable",
                    )
                ],
            )

        caption_text = target_table.rows[0][0] if target_table.rows else ""
        year = datetime.now().year
        row_date = parse_date_flexible(caption_text, default_year=year)
        if row_date is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="could not parse date from caption",
                warnings=[
                    ExtractorWarning(
                        code="no_date",
                        message=f"could not parse date from: {caption_text}",
                        target_label="timetable",
                    )
                ],
            )

        prayer_map = {
            "fajr": Prayer.FAJR,
            "zuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        rows: list[ExtractorRow] = []
        for row_number, row in enumerate(target_table.rows[2:], start=3):
            if not row:
                continue
            prayer_name = row[0].strip().lower()
            prayer = prayer_map.get(prayer_name)
            if prayer is None:
                continue
            jamaat_idx = 2 if len(row) > 2 else None
            if jamaat_idx is None:
                continue
            raw_time = row[jamaat_idx].strip()
            if not raw_time:
                continue
            jamaat = coerce_time(raw_time, prayer=prayer.value)
            if jamaat is None:
                continue
            window = PLAUSIBLE_WINDOWS.get(prayer.value)
            if window and not (window[0] <= jamaat <= window[1]):
                continue
            rows.append(
                ExtractorRow(
                    date=row_date,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join(row),
                        selector=f"table row {row_number}",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no extractable rows")
        return ExtractorResult(rows=rows)
