from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_day_of_month, parse_month_name
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
    key = "stepney_shahjalal_mosque___cultural_centre_c11f557d"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("stepneyshahjalalmosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://stepneyshahjalalmosque.org.uk/full-year-timetable",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = html_helpers.extract_tables(html)

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        year = datetime.now().year

        prayer_indices = {
            Prayer.FAJR: 2,
            Prayer.DHUHR: 5,
            Prayer.ASR: 7,
            Prayer.MAGHRIB: 9,
            Prayer.ISHA: 11,
        }

        for table in tables:
            if not table.rows:
                continue

            month_name = table.rows[0][0].strip() if table.rows[0] else ""
            month = parse_month_name(month_name)
            if month is None:
                continue

            for row_data in table.rows[3:]:
                if len(row_data) < 12:
                    continue

                day_str = row_data[0].strip()
                day = parse_day_of_month(day_str)
                if day is None:
                    continue

                try:
                    row_date = date(year, month, day)
                except ValueError:
                    continue

                for prayer, idx in prayer_indices.items():
                    raw = row_data[idx].strip() if idx < len(row_data) else ""
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
                                raw_text=" | ".join(row_data),
                                selector=f"table {month_name} row {day}",
                            ),
                        )
                    )

        if not rows:
            return ExtractorResult(
                rows=rows,
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=rows, warnings=warnings)
