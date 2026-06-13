from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "thornton_heath_islamic_centre_d557d412"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("thislamiccentre.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://thislamiccentre.org/?section=prayer",
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

        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(rows=[], no_schedule_reason="no tables found")

        rows: list[ExtractorRow] = []

        for table in tables:
            table_rows = table.body()

            # Skip first 2 rows (header/subheader)
            for row in table_rows[2:]:
                if len(row) < 13:
                    continue

                try:
                    date_str = row[0]
                    if not date_str or not date_str[0].isdigit():
                        continue

                    day = int(date_str.split()[0])
                    date_obj = datetime(datetime.now().year, 6, day).date()

                    # Skip if Dhuhr Jamat is "*"
                    if row[7].strip() == "*":
                        continue

                    # Extract jamaat times (indices: 4, 7, 9, 10, 12)
                    prayer_times = [
                        (Prayer.FAJR, row[4]),
                        (Prayer.DHUHR, row[7]),
                        (Prayer.ASR, row[9]),
                        (Prayer.MAGHRIB, row[10]),
                        (Prayer.ISHA, row[12]),
                    ]

                    for prayer, time_str in prayer_times:
                        if time_str and time_str != "*":
                            jamaat = coerce_time(time_str, prayer=prayer.value)
                            if jamaat:
                                rows.append(
                                    ExtractorRow(
                                        date=date_obj,
                                        prayer=prayer,
                                        jamaat_time=jamaat,
                                        timezone=ctx.timezone,
                                        evidence=ctx.evidence(
                                            target_label="timetable",
                                            extractor_key=self.key,
                                            extractor_version=self.version,
                                            raw_text=f"{date_str} {prayer.value} {time_str}",
                                        ),
                                    )
                                )
                except (IndexError, ValueError):
                    continue

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no prayer times found",
            )

        return ExtractorResult(rows=rows)
