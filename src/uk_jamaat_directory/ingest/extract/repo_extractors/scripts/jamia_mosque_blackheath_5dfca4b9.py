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


class Extractor(BaseMosqueWebsiteExtractor):
    key = "jamia_mosque_blackheath_5dfca4b9"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("blackheathjamiamosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://blackheathjamiamosque.co.uk/prayer-timetable/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        tables = extract_tables(artifact.text())
        if not tables:
            return ExtractorResult(rows=[], no_schedule_reason="no table found")

        table = tables[0]
        body_rows = table.body()
        if not body_rows or len(body_rows) < 2:
            return ExtractorResult(rows=[], no_schedule_reason="table has no data rows")

        # Skip first body row (it's the sub-header: Jun, Dhu..., Start, Jamat, etc)
        data_rows = body_rows[1:]
        year = datetime.now().year

        rows: list[ExtractorRow] = []
        for row_num, row in enumerate(data_rows, start=1):
            if len(row) < 14 or not row[2].strip():
                continue

            day_str = row[2].strip()
            if not day_str.isdigit():
                continue

            try:
                day = int(day_str)
                row_date = date(year, 6, day)  # June 2026
            except ValueError:
                continue

            # Extract jamaat times: indices 5, 8, 10, 11, 13
            jamaat_times = {
                Prayer.FAJR: coerce_time(row[5].strip(), prayer="fajr") if len(row) > 5 else None,
                Prayer.DHUHR: coerce_time(row[8].strip(), prayer="dhuhr") if len(row) > 8 else None,
                Prayer.ASR: coerce_time(row[10].strip(), prayer="asr") if len(row) > 10 else None,
                Prayer.MAGHRIB: coerce_time(row[11].strip(), prayer="maghrib")
                if len(row) > 11
                else None,
                Prayer.ISHA: coerce_time(row[13].strip(), prayer="isha") if len(row) > 13 else None,
            }

            for prayer, jamaat_time in jamaat_times.items():
                if jamaat_time is None:
                    continue

                evidence = ctx.evidence(
                    target_label="timetable",
                    extractor_key=self.key,
                    extractor_version=self.version,
                    raw_text=" | ".join(row),
                    selector=f"table row {row_num}",
                )

                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        start_time=None,
                        timezone=ctx.timezone,
                        evidence=evidence,
                    )
                )

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no extractable rows")

        return ExtractorResult(rows=rows, warnings=[])
