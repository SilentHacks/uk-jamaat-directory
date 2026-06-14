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
    key = "cambridge_central_mosque_165d4c74"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("cambridgecentralmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self):
        super().__init__()
        self._targets = (
            TargetSpec(
                label="prayer-times",
                url="https://cambridgecentralmosque.org/prayer-times/",
                kind=TargetKind.HTML,
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

        # Find all border:0 tables containing prayer times
        tables = re.findall(
            r"<table[^>]*style=['\"]border:0['\"][^>]*>(.*?)</table>", html, re.DOTALL
        )

        for table_html in tables:
            # Extract date from colspan='7' cell
            date_match = re.search(r"<td[^>]*>([A-Za-z]+day,\s*\d+-\d+-\d+)", table_html)
            if not date_match:
                continue

            date_str = date_match.group(1).strip()
            try:
                date_obj = datetime.strptime(date_str, "%A, %d-%m-%Y").date()
            except ValueError:
                continue

            # Find the BEGINS/JAMA'AT row (using . to match quote character variants)
            times_match = re.search(
                r"<td[^>]*>BEGINS<br>JAMA.AT</td>((?:<td[^>]*>.*?</td>){6})", table_html
            )
            if not times_match:
                continue

            # Extract individual time cells
            cells_html = times_match.group(1)
            cells = re.findall(r"<td[^>]*>(.*?)</td>", cells_html, re.DOTALL)

            if len(cells) < 6:
                continue

            # Map cells to prayers (skip Sunrise at index 1)
            prayer_indices = [
                (Prayer.FAJR, 0),
                (Prayer.DHUHR, 2),
                (Prayer.ASR, 3),
                (Prayer.MAGHRIB, 4),
                (Prayer.ISHA, 5),
            ]

            for prayer, idx in prayer_indices:
                cell_html = cells[idx]
                # Split by <br> to get jamaat time (second part)
                parts = re.split(r"<br\s*/?>\s*", cell_html, flags=re.IGNORECASE)
                if len(parts) < 2:
                    continue

                jamaat_raw = parts[1].strip()

                # Skip Friday special case
                if "jum'a" in jamaat_raw.lower():
                    continue

                # Remove HTML tags
                jamaat_raw = re.sub(r"<[^>]+>", "", jamaat_raw).strip()

                jamaat_time = coerce_time(jamaat_raw, prayer=prayer.value)
                if jamaat_time is None:
                    continue

                rows.append(
                    ExtractorRow(
                        date=date_obj,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="prayer-times",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{date_str} {prayer.value} {jamaat_raw}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no prayer times found",
            )

        return ExtractorResult(rows=rows)
