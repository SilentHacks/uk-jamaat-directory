from datetime import datetime

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
    key = "pakistani_muslim_community_centre_0d6fc891"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("smethwickjamiamosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://smethwickjamiamosque.co.uk/",
            kind=TargetKind.RENDERED_HTML,
        ),
    )

    # Map common prayer name variants to Prayer enum
    PRAYER_NAMES = {
        "fajr": Prayer.FAJR,
        "zuhr": Prayer.DHUHR,
        "dhuhr": Prayer.DHUHR,
        "asr": Prayer.ASR,
        "maghrib": Prayer.MAGHRIB,
        "isha": Prayer.ISHA,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html_text = artifact.text()
        tables = extract_tables(html_text)

        rows = []
        for table in tables:
            # Skip tables that don't have Prayer, Begins, Iqamah headers
            # Try to find the right header row by looking for one with 3+ columns
            header_idx = None
            for i, row in enumerate(table.rows):
                if len(row) >= 3 and all(
                    keyword.lower() in " ".join(row).lower()
                    for keyword in ["prayer", "begins", "iqamah"]
                ):
                    header_idx = i
                    break

            if header_idx is None:
                continue

            # Extract rows after the header
            extracted_rows = self._extract_from_table(ctx, table, header_idx)
            rows.extend(extracted_rows)

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=rows)

    def _extract_from_table(self, ctx: ExtractContext, table, header_idx: int):
        rows = []
        today = datetime.now().date()

        for row in table.rows[header_idx + 1 :]:
            if len(row) < 3:
                continue

            # Skip Sunrise rows
            prayer_name = row[0].strip().lower()
            if "sunrise" in prayer_name:
                continue

            # Match prayer name
            prayer = self.PRAYER_NAMES.get(prayer_name)
            if not prayer:
                continue

            # Get iqamah time (column 2)
            iqamah_str = row[2].strip() if len(row) > 2 else ""
            if not iqamah_str:
                continue

            jamaat = coerce_time(iqamah_str, prayer=prayer.value)
            if jamaat is None:
                continue

            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    start_time=None,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join(row),
                        selector=f"prayer {prayer.value}",
                    ),
                )
            )

        return rows
