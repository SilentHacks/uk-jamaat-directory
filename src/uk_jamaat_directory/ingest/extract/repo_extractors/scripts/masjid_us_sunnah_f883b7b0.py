from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
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
    key = "masjid_us_sunnah_f883b7b0"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("masjid-us-sunnah.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjid-us-sunnah.com/",
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

        row_date = datetime.now().date()

        # The site embeds a small "Salah Timings" dropdown table with explicit Iqamah (Jamaat) column.
        # <table class="table table-borderless jamat-time"> ... <th>Namaz</th><th>Time</th><th>Iqamah</th>
        # Rows: <td><i...></i>Fajr</td><td>adhan</td><td>iqamah</td>
        # We target the Iqamah column as the jamaat time.
        prayer_rows: list[tuple[str, str, str]] = []
        for table in html_helpers.extract_tables(html):
            flat = " ".join(" ".join(r).lower() for r in table.rows)
            if "namaz" in flat and "iqamah" in flat:
                for r in table.rows[1:]:  # skip header
                    if len(r) < 3:
                        continue
                    # strip tags for label/time/iqamah
                    name = re.sub(r"<[^>]+>", " ", r[0]).strip()
                    begin = re.sub(r"<[^>]+>", " ", r[1]).strip()
                    iqamah = re.sub(r"<[^>]+>", " ", r[2]).strip()
                    if name and iqamah:
                        prayer_rows.append((name, begin, iqamah))
                if prayer_rows:
                    break

        # Fallback regex for the exact structure if table extraction misses classes
        if not prayer_rows:
            matches = re.findall(
                r"<td[^>]*>\s*<i[^>]*></i>\s*([^<]+?)</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>",
                html,
                re.I | re.S,
            )
            for name, begin, iq in matches:
                name = name.strip()
                begin = (begin or "").strip()
                iq = (iq or "").strip()
                if name and iq:
                    prayer_rows.append((name, begin, iq))

        for prayer_label, begins, iqamah in prayer_rows:
            prayer_label = prayer_label.strip()
            begins = (begins or "").strip()
            iqamah = (iqamah or "").strip()

            prayer = parse_prayer_label(prayer_label)
            if prayer is None:
                # handle spelling variants present on site ("Magrib", "Zuhr")
                pl = prayer_label.lower()
                if "magrib" in pl:
                    prayer = Prayer.MAGHRIB
                elif "zuhr" in pl or "dhuhr" in pl:
                    prayer = Prayer.DHUHR
                elif "fajr" in pl:
                    prayer = Prayer.FAJR
                elif "asr" in pl:
                    prayer = Prayer.ASR
                elif "isha" in pl:
                    prayer = Prayer.ISHA
                else:
                    continue
            if prayer == Prayer.JUMUAH:
                continue

            jamaat = coerce_time(iqamah, prayer=prayer.value)
            if jamaat is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{row_date} {prayer.value}: {iqamah!r}",
                        target_label="timetable",
                    )
                )
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
                        selector="jamat-time table row",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )

        # Stable order by canonical prayer order
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
