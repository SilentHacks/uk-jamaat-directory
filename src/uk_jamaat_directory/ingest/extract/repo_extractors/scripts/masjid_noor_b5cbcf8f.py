from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import dates as date_helpers
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers import times as time_helpers
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
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
    key = "masjid_noor_b5cbcf8f"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("masjidnoor.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidnoor.org.uk/",
            kind=TargetKind.HTML,
        ),
    )

    _prayer_name_to_enum = {
        "fajr": Prayer.FAJR,
        "zuhr": Prayer.DHUHR,
        "asr": Prayer.ASR,
        "maghrib": Prayer.MAGHRIB,
        "isha": Prayer.ISHA,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        tables = html_helpers.extract_tables(artifact.text())
        for table in tables:
            if len(table.rows) < 3:
                continue
            header = table.rows[1]
            if not html_helpers.header_matches(header, ("prayer", "begins")):
                continue

            date_row = table.rows[0]
            row_date = date_helpers.parse_date_flexible(
                date_row[0], default_year=datetime.now().year
            )
            if row_date is None:
                continue

            rows: list[ExtractorRow] = []
            for body_row in table.rows[2:]:
                if not body_row or not body_row[0]:
                    continue

                prayer_name = body_row[0].strip().lower()
                prayer_enum = self._prayer_name_to_enum.get(prayer_name)
                if prayer_enum is None:
                    continue

                jamaat_time_str = body_row[2].strip() if len(body_row) > 2 else ""
                if not jamaat_time_str:
                    continue

                jamaat = time_helpers.coerce_time(jamaat_time_str, prayer=prayer_enum.value)
                if jamaat is None:
                    continue

                start_time_str = body_row[1].strip() if len(body_row) > 1 else ""
                start = None
                if start_time_str:
                    start = time_helpers.coerce_time(start_time_str, prayer=prayer_enum.value)

                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer_enum,
                        jamaat_time=jamaat,
                        start_time=start,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(body_row),
                            selector=f"table row {prayer_name}",
                        ),
                    )
                )

            if rows:
                return ExtractorResult(rows=rows, warnings=[])

        return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")
