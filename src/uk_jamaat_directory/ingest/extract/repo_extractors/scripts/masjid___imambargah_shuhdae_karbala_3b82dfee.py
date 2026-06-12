import re
from datetime import datetime, date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
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
    key = "masjid___imambargah_shuhdae_karbala_3b82dfee"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("shuhdaekarbala.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://shuhdaekarbala.org.uk/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()

        prayer_data = self._extract_prayer_times(html)
        if not prayer_data:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_prayer_data",
                        message="could not extract prayer times",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no extractable rows",
            )

        rows: list[ExtractorRow] = []
        row_date = datetime.now().date()

        for prayer_label, begins_time, iqamah_time in prayer_data:
            prayer = parse_prayer_label(prayer_label)
            if prayer is None:
                continue

            jamaat = coerce_time(iqamah_time, prayer=prayer.value)
            if jamaat is None:
                continue

            start = None
            if begins_time:
                start = coerce_time(begins_time, prayer=prayer.value)

            rows.append(
                ExtractorRow(
                    date=row_date,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    start_time=start,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=f"{prayer_label} | {begins_time} | {iqamah_time}",
                        selector="dptTimetable prayer row",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no extractable rows",
            )

        rows.sort(key=lambda r: (r.date, self._prayer_order(r.prayer)))
        return ExtractorResult(rows=rows)

    def _prayer_order(self, prayer: Prayer) -> int:
        order = {
            Prayer.FAJR: 0,
            Prayer.DHUHR: 1,
            Prayer.ASR: 2,
            Prayer.MAGHRIB: 3,
            Prayer.ISHA: 4,
        }
        return order.get(prayer, 999)

    def _extract_prayer_times(self, html: str) -> list[tuple[str, str, str]]:
        results = []

        prayer_rows = re.findall(
            r'<th[^>]*class="prayerName[^"]*">([^<]+)</th>\s*<td[^>]*class="begins[^"]*">([^<]+)</td>\s*<td[^>]*class="jamah[^"]*">([^<]+)</td>',
            html,
            re.DOTALL,
        )

        for prayer_label, begins, iqamah in prayer_rows:
            prayer_label = prayer_label.strip()
            begins = begins.strip()
            iqamah = iqamah.strip()

            if prayer_label and iqamah:
                results.append((prayer_label, begins, iqamah))

        return results
