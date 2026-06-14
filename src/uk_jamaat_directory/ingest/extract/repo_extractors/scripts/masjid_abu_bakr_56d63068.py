import re
from datetime import datetime

from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
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


class Extractor(BaseMosqueWebsiteExtractor):
    key = "masjid_abu_bakr_56d63068"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("masjidabubakr.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="homepage prayer times",
            url="https://masjidabubakr.co.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("homepage prayer times")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()

        # Extract prayer rows from the table using regex
        # Pattern: <th>Prayer Name</th><td>Time</td><td>Time</td>
        pattern = r"<th[^>]*>(\w+)</th>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>"
        matches = re.findall(pattern, html)

        if not matches:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table_rows",
                        message="prayer times rows not found",
                        target_label="homepage prayer times",
                    )
                ],
                no_schedule_reason="timetable rows not found",
            )

        today = datetime.now().date()
        rows = []
        warnings = []

        for row_num, (prayer_text, begins_text, iqamah_text) in enumerate(matches, start=1):
            prayer_text = prayer_text.strip()
            iqamah_text = iqamah_text.strip()

            # Skip Sunrise
            if prayer_text.lower() == "sunrise" or not iqamah_text:
                continue

            prayer = parse_prayer_label(prayer_text)
            if prayer is None:
                continue

            jamaat = coerce_time(iqamah_text, prayer=prayer.value)
            if jamaat is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"row {row_num} {prayer.value}: {iqamah_text!r}",
                        target_label="homepage prayer times",
                    )
                )
                continue

            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="homepage prayer times",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=f"{prayer_text} | {begins_text} | {iqamah_text}",
                        selector=f"table row {row_num}",
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
