from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
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
    key = "masjid_bilal_6c40d256"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("mbilal.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://mbilal.org/namaz-timetables/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        prayer_rows = re.findall(
            r'<th[^>]*class="prayerName[^"]*">([^<]+)</th>\s*<td[^>]*class="begins[^"]*">([^<]+)</td>\s*<td[^>]*class="jamah[^"]*">([^<]+)</td>',
            html,
            re.DOTALL | re.IGNORECASE,
        )

        row_date = datetime.now().date()

        for prayer_label, begins, iqamah in prayer_rows:
            prayer_label = prayer_label.strip()
            begins = begins.strip()
            iqamah = iqamah.strip()

            prayer = parse_prayer_label(prayer_label)
            if prayer is None or prayer == Prayer.JUMUAH:
                continue

            jamaat = coerce_time(iqamah, prayer=prayer.value)
            if jamaat is None:
                continue

            window = PLAUSIBLE_WINDOWS.get(prayer.value)
            if window and not (window[0] <= jamaat <= window[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"{row_date} {prayer.value}: {iqamah!r} outside plausible window",
                        target_label="timetable",
                    )
                )
                continue

            start = coerce_time(begins, prayer=prayer.value) if begins else None

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
                        raw_text=f"{prayer_label} | {begins} | {iqamah}",
                        selector="dptTimetable prayer row",
                    ),
                )
            )

        jumuah_match = re.search(
            r'<th[^>]*class="prayerName[^"]*">\s*<span[^>]*>\s*Jumu[^<]*</span>\s*</th>\s*<td[^>]*class="jamah[^"]*">(.*?)</td>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if jumuah_match:
            cell_html = jumuah_match.group(1)
            times: list[str] = [
                t.strip() for t in re.findall(r">([^<]+?)<", cell_html) if t.strip() and ":" in t
            ]
            if not times:
                text = re.sub(r"<[^>]+>", " ", cell_html)
                times = [t.strip() for t in re.split(r"\s*\|\s*", text) if t.strip() and ":" in t]
            for sidx, t in enumerate(times, 1):
                jt = coerce_time(t, prayer=Prayer.JUMUAH.value)
                if jt is None:
                    continue
                win = PLAUSIBLE_WINDOWS.get(Prayer.JUMUAH.value)
                if win and not (win[0] <= jt <= win[1]):
                    continue
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=Prayer.JUMUAH,
                        jamaat_time=jt,
                        start_time=None,
                        session_number=sidx,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=t,
                            selector="dptTimetable jumuah cell",
                        ),
                    )
                )

        if not rows:
            iqamahs = [iq.strip().lower() for _, _, iq in prayer_rows]
            if iqamahs and all(i.startswith("12:00") for i in iqamahs):
                return ExtractorResult(rows=[], no_schedule_reason="pdf target — awaiting parser")
            return ExtractorResult(rows=[], no_schedule_reason="no extractable rows")

        order = {
            Prayer.FAJR: 0,
            Prayer.DHUHR: 1,
            Prayer.ASR: 2,
            Prayer.MAGHRIB: 3,
            Prayer.ISHA: 4,
            Prayer.JUMUAH: 5,
        }
        rows.sort(key=lambda r: (r.date, order.get(r.prayer, 999), r.session_number))

        return ExtractorResult(rows=rows, warnings=warnings)
