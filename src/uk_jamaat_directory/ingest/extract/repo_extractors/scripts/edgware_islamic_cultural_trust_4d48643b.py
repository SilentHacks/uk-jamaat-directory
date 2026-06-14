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

DATE_RE = re.compile(r"(\w+ \d{1,2}, \d{4})")


class Extractor(BaseMosqueWebsiteExtractor):
    key = "edgware_islamic_cultural_trust_4d48643b"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("edgwareict.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://edgwareict.org.uk/monitor",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()

        date_match = DATE_RE.search(html)
        if date_match:
            row_date = parse_date_flexible(date_match.group(1), default_year=datetime.now().year)
        else:
            row_date = None

        if row_date is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_date",
                        message="date not found in page",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="date not found in page",
            )

        tables = extract_tables(html)
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

        prayer_table = None
        for table in tables:
            if not table.rows:
                continue
            header = [c.lower().strip() for c in table.rows[0]]
            if "prayer" in header and "begins" in header:
                prayer_table = table
                break

        if prayer_table is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_prayer_table",
                        message="no table with PRAYER/BEGINS header",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="prayer table not found",
            )

        parsed_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        for row_number, row in enumerate(prayer_table.rows[1:], start=2):
            if len(row) < 2:
                continue

            prayer_name = row[0].strip().lower()

            prayer = PRAYER_NAMES.get(prayer_name)
            if prayer is None:
                if "jumuah" in prayer_name:
                    jamaat_raw = row[1].strip() if len(row) >= 2 else ""
                    if jamaat_raw:
                        jamaat = coerce_time(jamaat_raw, prayer=Prayer.JUMUAH.value)
                        if jamaat:
                            parsed_rows.append(
                                ExtractorRow(
                                    date=row_date,
                                    prayer=Prayer.JUMUAH,
                                    jamaat_time=jamaat,
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
                continue

            if len(row) == 3:
                jamaat_raw = row[2].strip()
                start_raw = row[1].strip()
            elif len(row) == 2:
                continue
            else:
                continue

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
