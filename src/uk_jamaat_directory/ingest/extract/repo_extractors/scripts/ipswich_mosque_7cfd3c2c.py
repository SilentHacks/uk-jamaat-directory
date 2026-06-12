from datetime import date, datetime
from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
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

PRAYER_COL_MAP = [
    (3, Prayer.FAJR),
    (6, Prayer.DHUHR),
    (8, Prayer.ASR),
    (10, Prayer.MAGHRIB),
    (12, Prayer.ISHA),
]


class Extractor(BaseMosqueWebsiteExtractor):
    key = "ipswich_mosque_7cfd3c2c"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("ipswichmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://ipswichmosque.org/prayer_time.php",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = extract_tables(html)

        if not tables:
            return ExtractorResult(rows=[], no_schedule_reason="no tables found")

        table = tables[0]
        rows = table.rows

        # Skip title rows and find the actual header row with Date, Day, Begins
        header_row_idx = None
        for i, row in enumerate(rows):
            if any("date" in cell.lower() for cell in row):
                header_row_idx = i
                break

        if header_row_idx is None:
            return ExtractorResult(rows=[], no_schedule_reason="header row not found")

        body_rows = rows[header_row_idx + 1 :]

        result_rows = []
        seen = set()
        for row in body_rows:
            if not any(cell.strip() for cell in row):
                continue

            row_date = self._parse_date(row[0])
            if not row_date:
                continue

            # Skip rows with colspan or that are section separators
            if len(row) < 13:
                continue

            # Skip if we've already processed this date (avoid duplicates)
            if row_date in seen:
                continue
            seen.add(row_date)

            for col_idx, prayer in PRAYER_COL_MAP:
                if col_idx >= len(row):
                    continue

                raw = row[col_idx].strip()
                if not raw:
                    continue

                jamaat = coerce_time(raw, prayer=prayer.value)
                if jamaat is None:
                    continue

                result_rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        start_time=None,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{prayer.value}: {raw}",
                        ),
                        session_number=1,
                    )
                )

        if not result_rows:
            return ExtractorResult(rows=[], no_schedule_reason="no valid rows extracted")

        return ExtractorResult(rows=result_rows)

    def _parse_date(self, date_str: str) -> date | None:
        date_str = date_str.strip()
        try:
            day = int(date_str)
            now = datetime.now()
            return date(now.year, now.month, day)
        except (ValueError, TypeError):
            return None
