import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import parse_time_loose
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
    key = "jamia_masjid_ahl_e_hadith_2c012faf"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("web.archive.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://web.archive.org/web/20161216080151/www.greenlanemasjid.org/Prayer-Times",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()

        # Extract header from div-based prayer table
        div_pattern = r'<div class="p-prayer-table-row__cell">([^<]*)</div>'
        div_cells = re.findall(div_pattern, html)
        header = [c.strip() for c in div_cells]

        if not header:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no prayer table header found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        header_lower = [h.lower() for h in header]

        # Find column indices from header
        date_idx = None
        for idx, h in enumerate(header_lower):
            if "date" in h:
                date_idx = idx
                break

        if date_idx is None:
            return ExtractorResult(rows=[], no_schedule_reason="date column not found")

        # Map prayer labels to column indices
        prayer_map = {}
        for prayer, label in [
            (Prayer.FAJR, "fajr jamat"),
            (Prayer.DHUHR, "dhuhr jamat"),
            (Prayer.ASR, "asr jamat"),
            (Prayer.MAGHRIB, "maghrib"),
            (Prayer.ISHA, "isha jamat"),
        ]:
            for idx, h in enumerate(header_lower):
                if label in h:
                    prayer_map[prayer] = idx
                    break

        if not prayer_map:
            return ExtractorResult(rows=[], no_schedule_reason="no prayer columns found")

        # Extract data rows from li elements
        li_pattern = r'<li class="p-prayer-table-row__cell[^>]*>([^<]*)</li>'
        li_cells = re.findall(li_pattern, html)
        data_cells = [c.strip() for c in li_cells]

        if not data_cells:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no data cells found",
            )

        cols_per_row = len(header)
        extracted_rows = []
        year = datetime.now().year
        month = datetime.now().month

        # Process data rows
        for i in range(0, len(data_cells), cols_per_row):
            row = data_cells[i : i + cols_per_row]
            if len(row) < cols_per_row or i + cols_per_row > len(data_cells):
                continue

            if not row[date_idx].strip():
                continue

            date_cell = row[date_idx].strip()
            day_match = re.match(r"(\d+)(?:st|nd|rd|th)?", date_cell)
            if not day_match:
                continue

            try:
                day = int(day_match.group(1))
                row_date = date(year, month, day)
            except ValueError:
                continue

            for prayer, col_idx in prayer_map.items():
                jamaat_str = row[col_idx].strip() if col_idx < len(row) else ""
                if not jamaat_str:
                    continue

                jamaat_time = parse_time_loose(jamaat_str)
                if jamaat_time is None:
                    continue

                evidence = ctx.evidence(
                    target_label="timetable",
                    extractor_key=self.key,
                    extractor_version=self.version,
                    raw_text=jamaat_str,
                    selector=f"row {i // cols_per_row} col {col_idx}",
                )

                extracted_rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        start_time=None,
                        session_number=1,
                        timezone=ctx.timezone,
                        evidence=evidence,
                    )
                )

        if not extracted_rows:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_extractable_rows",
                        message="no extractable rows found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no extractable rows found",
            )

        return ExtractorResult(rows=extracted_rows, warnings=[])
