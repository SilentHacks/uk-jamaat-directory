from __future__ import annotations

import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
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
    key = "jamia_masjid_anwar_ul_uloom_6db7c9d1"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("smethwickjamiamosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://smethwickjamiamosque.co.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        # Extract date from the table title: "Namaz Times 12th June 2026"
        date_m = re.search(
            r"Namaz\s+Times\s+(\d{1,2})(?:st|nd|rd|th)?\s+"
            r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{4})",
            html,
            re.I,
        )
        if not date_m:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_date",
                        message="could not find date in table title",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="date not found in table title",
            )

        day = int(date_m.group(1))
        mon_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        month = mon_map.get(date_m.group(2).lower()[:3], datetime.now().month)
        year = int(date_m.group(3))
        row_date = date(year, month, day)

        prayer_map = {
            "Fajr": Prayer.FAJR,
            "Zuhr": Prayer.DHUHR,
            "Asr": Prayer.ASR,
            "Maghrib": Prayer.MAGHRIB,
            "Isha": Prayer.ISHA,
        }

        for label, prayer in prayer_map.items():
            # Find the row: <th>Fajr</th> ... <td class="jamah ...">4:00 am</td>
            pat = (
                rf"<th[^>]*>\s*{re.escape(label)}\s*</th>.*?"
                rf'<td[^>]*class\s*=\s*["\'][^"\']*jamah[^"\']*["\'][^>]*>([^<]+)</td>'
            )
            m = re.search(pat, html, re.I | re.S)
            if not m:
                continue
            raw = m.group(1).strip()
            jt = coerce_time(raw, prayer=prayer.value)
            if jt is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{row_date} {prayer.value}: {raw!r}",
                        target_label="timetable",
                    )
                )
                continue
            win = PLAUSIBLE_WINDOWS.get(prayer.value)
            if win and not (win[0] <= jt <= win[1]):
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
                    jamaat_time=jt,
                    start_time=None,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=raw,
                        selector=f"dptTimetable {label} jamah",
                    ),
                )
            )

        # Jumuah: look for a Jumuah row in the table or nearby text
        ju = re.search(
            r"<th[^>]*>\s*Jumu[ae]ah?\s*</th>.*?"
            r'<td[^>]*class\s*=\s*["\'][^"\']*jamah[^"\']*["\'][^>]*>([^<]+)</td>',
            html,
            re.I | re.S,
        )
        if ju:
            jraw = ju.group(1).strip()
            jt = coerce_time(jraw, prayer="jumuah")
            if jt is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{row_date} jumuah: {jraw!r}",
                        target_label="timetable",
                    )
                )
            else:
                win = PLAUSIBLE_WINDOWS.get("jumuah")
                if win and not (win[0] <= jt <= win[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{row_date} jumuah: {jraw!r} outside plausible window",
                            target_label="timetable",
                        )
                    )
                else:
                    rows.append(
                        ExtractorRow(
                            date=row_date,
                            prayer=Prayer.JUMUAH,
                            jamaat_time=jt,
                            start_time=None,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=jraw,
                                selector="dptTimetable Jumuah jamah",
                            ),
                        )
                    )

        if not rows:
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
