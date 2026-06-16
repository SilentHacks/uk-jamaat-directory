import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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
    key = "jamiat_ahl_e_hadith_fe8c209c"
    version = "2026.06.16.1"
    source_match = SourceMatch(domains=("greenlanemasjid.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://web.archive.org/web/20170114131528/http://www.greenlanemasjid.org/prayer-times/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="empty_artifact",
                        message="timetable artifact is empty",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="artifact was empty",
            )

        html = artifact.text()
        extracted_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        # Parse <ol class="p-prayer-table-row" prayer-date="DD-MM-YYYY"> rows
        # Each row has <li> elements with prayer-label attributes
        row_pattern = r'<ol\s+class="p-prayer-table-row"\s+prayer-date="(\d{2})-(\d{2})-(\d{4})"[^>]*>(.*?)</ol>'

        for row_match in re.finditer(row_pattern, html, re.DOTALL):
            day_str, month_str, year_str = (
                row_match.group(1),
                row_match.group(2),
                row_match.group(3),
            )
            row_html = row_match.group(4)

            try:
                row_date = parse_date_flexible(
                    f"{day_str}/{month_str}/{year_str}",
                    default_year=int(year_str) if year_str else datetime.now().year,
                )
                if row_date is None:
                    continue
            except Exception:
                continue

            # Extract prayer times from <li prayer-label="..."> elements
            prayers_map = {
                "fajr-jamat": Prayer.FAJR,
                "dhuhr-jamat": Prayer.DHUHR,
                "asr-jamat": Prayer.ASR,
                "maghrib": Prayer.MAGHRIB,
                "isha-jamat": Prayer.ISHA,
            }

            for label, prayer in prayers_map.items():
                # Match <li prayer-label="...">time</li>
                time_pattern = rf'<li\s+[^>]*prayer-label="{re.escape(label)}"[^>]*>([^<]+)</li>'
                time_match = re.search(time_pattern, row_html)

                if not time_match:
                    continue

                time_text = time_match.group(1).strip()
                jamaat_time = coerce_time(time_text, prayer=prayer.value)

                if jamaat_time is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {time_text!r}",
                            target_label="timetable",
                        )
                    )
                    continue

                evidence = ctx.evidence(
                    target_label="timetable",
                    extractor_key=self.key,
                    extractor_version=self.version,
                    raw_text=f"{day_str}/{month_str}/{year_str} {prayer.value} {time_text}",
                    selector=f"ol[prayer-date] li[prayer-label='{label}']",
                )
                extracted_rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        timezone=ctx.timezone,
                        evidence=evidence,
                    )
                )

        if not extracted_rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )

        return ExtractorResult(rows=extracted_rows, warnings=warnings)
