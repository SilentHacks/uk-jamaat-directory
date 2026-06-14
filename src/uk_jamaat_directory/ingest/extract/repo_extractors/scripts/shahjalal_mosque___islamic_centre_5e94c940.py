from datetime import date

from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
from uk_jamaat_directory.ingest.extract.helpers.times import parse_time_loose
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
    key = "shahjalal_mosque___islamic_centre_5e94c940"
    version = "2026.06.13.2"
    source_match = SourceMatch(domains=("shahjalalmasjid.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://shahjalalmasjid.org/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(rows=[], no_schedule_reason="image target — awaiting OCR")

        extracted_rows: list[ExtractorRow] = []
        for table in tables:
            for row_index, row in enumerate(table.body(), start=1):
                if len(row) < 3:
                    continue
                try:
                    parsed_date = date.fromisoformat(row[0])
                except ValueError:
                    continue

                prayer = parse_prayer_label(row[1])
                if prayer is None:
                    continue

                jamaat_time = parse_time_loose(row[2])
                if jamaat_time is None:
                    continue

                evidence = ctx.evidence(
                    target_label="timetable",
                    extractor_key=self.key,
                    extractor_version=self.version,
                    raw_text=" | ".join(row),
                )
                extracted_rows.append(
                    ExtractorRow(
                        date=parsed_date,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        timezone=ctx.timezone,
                        evidence=evidence,
                    )
                )

        return ExtractorResult(rows=extracted_rows)
