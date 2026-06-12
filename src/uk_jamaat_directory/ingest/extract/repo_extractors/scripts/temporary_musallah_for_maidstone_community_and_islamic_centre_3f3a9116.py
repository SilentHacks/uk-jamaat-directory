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
    key = "temporary_musallah_for_maidstone_community_and_islamic_centre_3f3a9116"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("maidstonemosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        self.targets = (
            TargetSpec(
                label="timetable",
                url=f"http://maidstonemosque.com/wp-admin/admin-ajax.php?action=get_monthly_timetable&month={now.month}&display=",
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
                warnings=[ExtractorWarning(code="no_table", message="no tables found in AJAX response")],
                no_schedule_reason="timetable table not found",
            )

        table = tables[0]
        body = table.body()
        if len(body) < 2:
            return ExtractorResult(
                rows=[],
                warnings=[ExtractorWarning(code="no_data", message="table has no data rows")],
                no_schedule_reason="no data rows in timetable",
            )

        subheader = body[0]
        data_rows = body[1:]

        if len(subheader) < 13:
            return ExtractorResult(
                rows=[],
                warnings=[ExtractorWarning(code="bad_header", message=f"unexpected column count: {len(subheader)}")],
                no_schedule_reason="unexpected table structure",
            )

        iqamah_indices = {
            Prayer.FAJR: 3,
            Prayer.DHUHR: 6,
            Prayer.ASR: 8,
            Prayer.MAGHRIB: 10,
            Prayer.ISHA: 12,
        }

        year = datetime.now().year
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        for row_number, row in enumerate(data_rows, start=3):
            if len(row) < 13:
                continue

            raw_date = row[0].strip()
            if not raw_date:
                continue

            row_date = parse_date_flexible(raw_date, default_year=year)
            if row_date is None:
                continue

            for prayer, idx in iqamah_indices.items():
                raw = row[idx].strip() if idx < len(row) else ""
                if not raw:
                    continue

                jamaat = coerce_time(raw, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue

                window = PLAUSIBLE_WINDOWS.get(prayer.value)
                if window and not (window[0] <= jamaat <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{row_date} {prayer.value}: {raw!r} outside plausible window",
                            target_label="timetable",
                        )
                    )
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
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )

        return ExtractorResult(rows=rows, warnings=warnings)
