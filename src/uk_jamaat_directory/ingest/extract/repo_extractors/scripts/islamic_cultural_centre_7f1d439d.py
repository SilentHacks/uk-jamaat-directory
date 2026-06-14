import re

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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
    key = "islamic_cultural_centre_7f1d439d"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("rhylmasjid.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://rhylmasjid.com/files/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = (
            artifact.body.decode("utf-8", errors="ignore")
            if isinstance(artifact.body, bytes)
            else artifact.body
        )

        rows: list[ExtractorRow] = []

        # Extract date from page header: "Saturday • 13 June 2026"
        date_match = re.search(
            r"(\d+)\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
            html,
        )
        if not date_match:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="could not find date in page header",
            )

        day, month_str, year_str = date_match.groups()
        date_str = f"{day} {month_str} {year_str}"
        parsed_date = parse_date_flexible(date_str, default_year=int(year_str))
        if not parsed_date:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="could not parse date from page",
            )

        # Find the table with class="st_hr_table"
        table_match = re.search(
            r'<table[^>]*class="st_hr_table"[^>]*>(.*?)</table>', html, re.DOTALL
        )
        if not table_match:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable table not found",
            )

        table_html = table_match.group(1)

        # Extract rows
        tr_matches = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL)
        if not tr_matches:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no table rows found",
            )

        # First row is header, skip it
        if len(tr_matches) < 2:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="insufficient table rows",
            )

        # Extract header to determine column positions
        header_cells = re.findall(r"<th[^>]*>([^<]*)</th>", tr_matches[0])
        # Skip empty first column
        header_lower = [h.strip().lower() for h in header_cells[1:]]

        # Find Jama'ah row (should be 3rd row after header)
        jamaat_row_html = None
        for tr in tr_matches[1:]:
            # Check for both "jama'ah" and HTML-encoded version
            if "jama" in tr.lower():
                jamaat_row_html = tr
                break

        if not jamaat_row_html:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no jamaat row found",
            )

        # Extract times from Jama'ah row
        jamaat_cells_raw = re.findall(r"<td[^>]*>([^<]+)</td>", jamaat_row_html)

        # Skip first cell (label), get times starting from index 1
        if len(jamaat_cells_raw) < 2:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="insufficient cells in jamaat row",
            )

        jamaat_cells = jamaat_cells_raw[1:]  # Skip the label

        # The Sunrise column is missing from Jama'ah row due to rowspan in Begins row
        # Insert empty string at position 1 (between Fajr and Zuhr) to align columns
        jamaat_cells_aligned = [
            jamaat_cells[0],  # Fajr
            "",  # Sunrise (missing, but reserve position)
            jamaat_cells[1],  # Zuhr (now at index 2 after insert)
            jamaat_cells[2],  # Asr
            jamaat_cells[3],  # Magrib
            jamaat_cells[4],  # Isha
        ]

        # Map prayer names to header keywords and extract times
        prayer_map = {
            Prayer.FAJR: "fajr",
            Prayer.DHUHR: "zuhr",
            Prayer.ASR: "asr",
            Prayer.MAGHRIB: "magrib",
            Prayer.ISHA: "isha",
        }

        for prayer, keyword in prayer_map.items():
            col_idx = None
            for i, h in enumerate(header_lower):
                if keyword in h:
                    col_idx = i
                    break

            if col_idx is None or col_idx >= len(jamaat_cells_aligned):
                continue

            time_str = jamaat_cells_aligned[col_idx].strip()
            if not time_str:
                continue
            jamaat_time = coerce_time(time_str, prayer=prayer.value)
            if jamaat_time:
                rows.append(
                    ExtractorRow(
                        date=parsed_date,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{prayer.value} {jamaat_time}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no jamaat times extracted",
            )

        return ExtractorResult(rows=rows)
