import re
from datetime import date as date_type

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
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
    key = "swindon_masjid_5426174c"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("swindonmasjid.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.swindonmasjid.com/wp-content/uploads/st.php?source=homepage",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        body = ctx.artifact("timetable")
        if not body.body:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="empty_artifact",
                        message="timetable artifact is empty",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="artifact was empty",
            )

        html = body.text()
        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no table found in timetable",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no table present",
            )

        table = tables[0]
        header = [cell.strip().lower() for cell in table.header]

        # Extract date from caption (e.g., "Prayer Time for Today (2026-06-13)")
        caption_match = re.search(r"\((\d{4})-(\d{2})-(\d{2})\)", html)
        if not caption_match:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_date",
                        message="could not find date in table caption",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="date not found",
            )

        try:
            table_date = date_type(
                int(caption_match.group(1)),
                int(caption_match.group(2)),
                int(caption_match.group(3)),
            )
        except ValueError:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="bad_date",
                        message="invalid date in caption",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="invalid date",
            )

        # Find column indices
        jamaat_col = None
        for idx, cell in enumerate(header):
            if "jamaat" in cell:
                jamaat_col = idx
                break

        if jamaat_col is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_jamaat_column",
                        message="jamaat column not found in header",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="jamaat column not found",
            )

        extracted_rows = []
        warnings = []

        for row_idx, row in enumerate(table.body(), start=1):
            if len(row) < jamaat_col + 1:
                continue

            prayer_cell = row[0].strip()
            jamaat_cell = row[jamaat_col].strip()

            # Skip sunrise row
            if "sunrise" in prayer_cell.lower():
                continue

            # Normalize prayer names (e.g., "Zuhur" -> "Zuhr")
            normalized = prayer_cell.lower()
            if normalized == "zuhur":
                normalized = "zuhr"
            elif normalized == "magrib":
                normalized = "maghrib"
            
            prayer = parse_prayer_label(normalized)
            if prayer is None:
                warnings.append(
                    ExtractorWarning(
                        code="unknown_prayer",
                        message=f"row {row_idx}: unknown prayer '{prayer_cell}'",
                        target_label="timetable",
                    )
                )
                continue

            jamaat_time = coerce_time(jamaat_cell, prayer=prayer.value)
            if jamaat_time is None:
                warnings.append(
                    ExtractorWarning(
                        code="bad_jamaat",
                        message=f"row {row_idx}: invalid jamaat time '{jamaat_cell}'",
                        target_label="timetable",
                    )
                )
                continue

            session_number = 1
            session_label = None
            if prayer.value == "jumuah":
                jumuah_count = len(
                    [r for r in extracted_rows if r.prayer.value == "jumuah"]
                )
                session_number = jumuah_count + 1
                session_label = f"session {session_number}"

            evidence = ctx.evidence(
                target_label="timetable",
                extractor_key=self.key,
                extractor_version=self.version,
                raw_text=f"{prayer_cell} | {jamaat_cell}",
                selector=f"table tbody tr:nth-child({row_idx})",
            )

            extracted_rows.append(
                ExtractorRow(
                    date=table_date,
                    prayer=prayer,
                    jamaat_time=jamaat_time,
                    session_number=session_number,
                    session_label=session_label,
                    timezone=ctx.timezone,
                    evidence=evidence,
                )
            )

        if not extracted_rows and not warnings:
            warnings.append(
                ExtractorWarning(
                    code="no_extractable_rows",
                    message="no extractable prayer rows found",
                    target_label="timetable",
                )
            )

        return ExtractorResult(rows=extracted_rows, warnings=warnings)
