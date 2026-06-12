import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
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

PRAYER_NAMES: dict[str, Prayer] = {
    "fajr": Prayer.FAJR,
    "zuhr": Prayer.DHUHR,
    "asr": Prayer.ASR,
    "maghrib": Prayer.MAGHRIB,
    "isha": Prayer.ISHA,
}

DATE_PATTERN = re.compile(r"(\d{1,2}\s+\w+\s+\d{4})")


class Extractor(BaseMosqueWebsiteExtractor):
    key = "harrow_central_mosque_3bf64ecc"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("harrowmosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://harrowmosque.org.uk/",
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
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no tables found on page",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        table = tables[0]

        rows = table.rows
        if len(rows) < 3:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="too_few_rows",
                        message=f"table has only {len(rows)} rows",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="too few table rows",
            )

        date_match = DATE_PATTERN.search(rows[0][0])
        if not date_match:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_date",
                        message=f"no date found in header: {rows[0][0]!r}",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="date not found in table header",
            )
        row_date = parse_date_flexible(date_match.group(1), default_year=datetime.now().year)
        if row_date is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="bad_date",
                        message=f"unparseable date: {date_match.group(1)!r}",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="unparseable date",
            )

        parsed_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        for row_number, row in enumerate(rows[2:], start=3):
            if len(row) < 3:
                continue
            prayer_name = row[0].strip().rstrip("*").lower()
            prayer = PRAYER_NAMES.get(prayer_name)
            if prayer is None:
                continue

            jamaat_raw = row[2].strip()
            if not jamaat_raw:
                continue
            jamaat = coerce_time(jamaat_raw, prayer=prayer.value)
            if jamaat is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{row_date} {prayer.value}: jamaat={jamaat_raw!r}",
                        target_label="timetable",
                    )
                )
                continue

            start_raw = row[1].strip()
            start = coerce_time(start_raw, prayer=prayer.value) if start_raw else None

            parsed_rows.append(
                ExtractorRow(
                    date=row_date,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    start_time=start,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join(row),
                        selector=f"table tr:nth-child({row_number})",
                    ),
                )
            )

        if not parsed_rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=parsed_rows, warnings=warnings)
