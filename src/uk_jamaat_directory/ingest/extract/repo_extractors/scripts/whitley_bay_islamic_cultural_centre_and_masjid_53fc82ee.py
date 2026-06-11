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
    key = "whitley_bay_islamic_cultural_centre_and_masjid_53fc82ee"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("wbicc.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://wbicc.org.uk/prayer-times",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
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
                        code="no_table",
                        message="no tables found in page",
                        target_label="timetable",
                    )
                ],
            )

        target_table = None
        for table in tables:
            header_lower = [cell.lower() for cell in table.header]
            if any("fajr" in cell for cell in header_lower):
                target_table = table
                break

        if target_table is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable table not found",
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no table with Fajr column in header",
                        target_label="timetable",
                    )
                ],
            )

        header = target_table.header
        header_lower = [cell.lower() for cell in header]
        body = target_table.rows

        prayer_columns = {}
        prayer_map = {
            "fajr": Prayer.FAJR,
            "zuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        for prayer_name, prayer_enum in prayer_map.items():
            for idx, cell in enumerate(header_lower):
                if prayer_name in cell:
                    prayer_columns[prayer_enum] = idx
                    break

        if not prayer_columns:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no prayer columns found",
                warnings=[
                    ExtractorWarning(
                        code="no_prayer_columns",
                        message="no prayer columns matched in header",
                        target_label="timetable",
                    )
                ],
            )

        jamaat_row = None
        for idx, row in enumerate(body):
            if not row or len(row) == 0:
                continue
            first_cell_lower = row[0].lower()
            if any(keyword in first_cell_lower for keyword in ["jamaa", "jama"]):
                jamaat_row = row
                break

        if jamaat_row is None:
            if len(body) >= 2:
                jamaat_row = body[1]
            else:
                return ExtractorResult(
                    rows=[],
                    no_schedule_reason="jamaat row not found",
                    warnings=[
                        ExtractorWarning(
                            code="no_jamaat_row",
                            message="Jama'at row not found in table",
                            target_label="timetable",
                        )
                    ],
                )

        rows: list[ExtractorRow] = []
        today = datetime.now().date()

        for prayer, col_idx in prayer_columns.items():
            if col_idx >= len(jamaat_row):
                continue

            raw_time = jamaat_row[col_idx].strip()
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
                    date=today,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=raw_time,
                        selector=f"jamaat row, {prayer.value} column",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no extractable rows",
            )

        return ExtractorResult(rows=rows)
