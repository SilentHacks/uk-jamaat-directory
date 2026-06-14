from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorEvidence,
    ExtractorResult,
    ExtractorRow,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    BaseMosqueWebsiteExtractor,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "al_falah_community_centre_0bbbeab7"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("alfalahmasjidluton.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://timing.athanplus.com/masjid/widgets/monthly?theme=2&masjid_id=JAm7JRKR",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        target_label = self.targets[0].label
        artifact = ctx.artifact(target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        rows_data = []

        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(rows=[], no_schedule_reason="no table found")

        main_table = tables[0]
        table_rows = main_table.body()

        for table_row in table_rows:
            if len(table_row) < 13:
                continue

            day_num = table_row[0].strip()
            if not day_num or not day_num[0].isdigit():
                continue

            date_str = f"{day_num} June 2026"
            try:
                parsed_date = parse_date_flexible(date_str, default_year=2026)
                if not parsed_date:
                    continue
            except Exception:
                continue

            # IQAMAH times: cell 4 (fajr), 7 (dhuhr), 9 (asr), 12 (isha)
            jamaat_times = {
                Prayer.FAJR: table_row[4] if len(table_row) > 4 else "",
                Prayer.DHUHR: table_row[7] if len(table_row) > 7 else "",
                Prayer.ASR: table_row[9] if len(table_row) > 9 else "",
                Prayer.ISHA: table_row[12] if len(table_row) > 12 else "",
            }

            evidence = ExtractorEvidence(
                target_label=target_label,
                target_url=artifact.target_url,
                extractor_key=self.key,
                extractor_version=self.version,
            )

            for prayer, jamaat_str in jamaat_times.items():
                jamaat_time = coerce_time(jamaat_str, prayer=prayer.value)
                if jamaat_time:
                    row = ExtractorRow(
                        date=parsed_date,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        evidence=evidence,
                    )
                    rows_data.append(row)

        return (
            ExtractorResult(rows=rows_data)
            if rows_data
            else ExtractorResult(rows=[], no_schedule_reason="no data rows extracted")
        )
