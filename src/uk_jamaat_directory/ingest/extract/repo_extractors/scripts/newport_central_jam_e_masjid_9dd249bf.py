import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
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
    key = "newport_central_jam_e_masjid_9dd249bf"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("ncjm.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self):
        super().__init__()
        self._targets = (
            TargetSpec(
                label="prayer-times",
                url="https://ncjm.co.uk/prayer-times",
                kind=TargetKind.RENDERED_HTML,
            ),
        )

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("prayer-times")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = (
            artifact.body.decode("utf-8", errors="ignore")
            if isinstance(artifact.body, bytes)
            else artifact.body
        )

        rows: list[ExtractorRow] = []

        # Look for prayer time tables in various common formats
        # Pattern 1: Table with date, fajr, dhuhr, asr, maghrib, isha headers
        table_pattern = r"<table[^>]*>(.*?)</table>"
        tables = re.findall(table_pattern, html, re.DOTALL | re.IGNORECASE)

        for table_html in tables:
            # Extract header row
            header_cells = re.findall(r"<th[^>]*>([^<]+)</th>|<td[^>]*>([^<]+)</td>", 
                                     table_html[:1000], re.IGNORECASE)
            if not header_cells:
                continue

            # Flatten tuples and clean
            headers = [cell[0] or cell[1] for cell in header_cells]
            headers_lower = [h.lower().strip() for h in headers]

            # Check if this looks like a prayer timetable
            if not any("date" in h or "day" in h for h in headers_lower):
                continue
            if not any("fajr" in h or "zuhr" in h or "asr" in h for h in headers_lower):
                continue

            # Find column indices
            date_idx = None
            prayer_indices = {}

            for idx, h in enumerate(headers_lower):
                if "date" in h or "day" in h:
                    date_idx = idx
                if "fajr" in h:
                    prayer_indices[Prayer.FAJR] = idx
                elif "zuhr" in h or "dhuhr" in h:
                    prayer_indices[Prayer.DHUHR] = idx
                elif "asr" in h:
                    prayer_indices[Prayer.ASR] = idx
                elif "maghrib" in h:
                    prayer_indices[Prayer.MAGHRIB] = idx
                elif "isha" in h:
                    prayer_indices[Prayer.ISHA] = idx

            if date_idx is None or len(prayer_indices) < 5:
                continue

            # Extract data rows
            row_pattern = r"<tr[^>]*>(.*?)</tr>"
            rows_html = re.findall(row_pattern, table_html, re.DOTALL | re.IGNORECASE)

            for row_html in rows_html[1:]:  # Skip header row
                cells = re.findall(r"<td[^>]*>([^<]*)</td>", row_html, re.IGNORECASE)
                if not cells or date_idx >= len(cells):
                    continue

                date_str = cells[date_idx].strip()
                if not date_str:
                    continue

                try:
                    row_date = datetime.strptime(date_str, "%d/%m/%Y").date()
                except (ValueError, IndexError):
                    try:
                        row_date = datetime.strptime(date_str, "%d-%m-%Y").date()
                    except ValueError:
                        continue

                # Extract jamaat times for each prayer
                for prayer, idx in prayer_indices.items():
                    if idx >= len(cells):
                        continue
                    
                    time_str = cells[idx].strip()
                    if not time_str:
                        continue

                    jamaat_time = coerce_time(time_str, prayer=prayer.value)
                    if jamaat_time is None:
                        continue

                    rows.append(
                        ExtractorRow(
                            date=row_date,
                            prayer=prayer,
                            jamaat_time=jamaat_time,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="prayer-times",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"{date_str} {prayer.value} {time_str}",
                            ),
                        )
                    )

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no prayer times found in table",
            )

        return ExtractorResult(rows=rows)
