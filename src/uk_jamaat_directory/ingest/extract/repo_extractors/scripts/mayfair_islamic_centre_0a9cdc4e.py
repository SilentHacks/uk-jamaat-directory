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
    key = "mayfair_islamic_centre_0a9cdc4e"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("mayfairislamiccentre.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://mayfairislamiccentre.org.uk/042026.csv",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        csv_content = (
            artifact.body.decode("utf-8", errors="ignore")
            if isinstance(artifact.body, bytes)
            else artifact.body
        )

        lines = csv_content.strip().split("\n")
        if not lines:
            return ExtractorResult(rows=[], no_schedule_reason="no data in CSV")

        rows: list[ExtractorRow] = []
        current_month = str(datetime.now().month).zfill(2)
        current_year = datetime.now().year

        for line in lines[1:]:
            if not line.strip():
                continue

            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 14:
                continue

            day_str = parts[0]
            month_str = parts[1]

            if month_str != current_month:
                continue

            try:
                day = int(day_str)
                prayer_date = datetime(current_year, int(month_str), day).date()
            except (ValueError, IndexError):
                continue

            fajr_time = coerce_time(parts[9], prayer=Prayer.FAJR)
            dhuhr_time = coerce_time(parts[10], prayer=Prayer.DHUHR)
            asr_time = coerce_time(parts[11], prayer=Prayer.ASR)
            maghrib_time = coerce_time(parts[12], prayer=Prayer.MAGHRIB)
            isha_time = coerce_time(parts[13], prayer=Prayer.ISHA)

            if fajr_time:
                rows.append(
                    ExtractorRow(
                        date=prayer_date,
                        prayer=Prayer.FAJR,
                        jamaat_time=fajr_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{day_str} Fajr {fajr_time}",
                        ),
                    )
                )
            if dhuhr_time:
                rows.append(
                    ExtractorRow(
                        date=prayer_date,
                        prayer=Prayer.DHUHR,
                        jamaat_time=dhuhr_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{day_str} Dhuhr {dhuhr_time}",
                        ),
                    )
                )
            if asr_time:
                rows.append(
                    ExtractorRow(
                        date=prayer_date,
                        prayer=Prayer.ASR,
                        jamaat_time=asr_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{day_str} Asr {asr_time}",
                        ),
                    )
                )
            if maghrib_time:
                rows.append(
                    ExtractorRow(
                        date=prayer_date,
                        prayer=Prayer.MAGHRIB,
                        jamaat_time=maghrib_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{day_str} Maghrib {maghrib_time}",
                        ),
                    )
                )
            if isha_time:
                rows.append(
                    ExtractorRow(
                        date=prayer_date,
                        prayer=Prayer.ISHA,
                        jamaat_time=isha_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{day_str} Isha {isha_time}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no prayer times found")

        return ExtractorResult(rows=rows)
