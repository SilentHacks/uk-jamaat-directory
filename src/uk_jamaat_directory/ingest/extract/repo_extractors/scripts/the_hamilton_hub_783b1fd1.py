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
    key = "the_hamilton_hub_783b1fd1"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("dfhtrust.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://dfhtrust.org/salah-times/",
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

        # The page renders a today-only table with columns: Salah | Begin | Jamat
        # Example header: <th>Salah</th><th>Begin</th><th>Jamat</th>
        # Rows use <strong>Fajr</strong> etc inside the first cell; "Jamat" is iqamah.
        prayer_rows = re.findall(
            r"<td[^>]*>\s*<i[^>]*></i>\s*<strong>([^<]+)</strong>\s*</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>",
            html,
            re.I | re.S,
        )
        if not prayer_rows:
            # Fallback: any three <td> cells in a row under a table that has Begin/Jamat headers
            for t in html_helpers.extract_tables(html):
                flat = " ".join(" ".join(r).lower() for r in t.rows)
                if "begin" in flat and "jamat" in flat and ("fajr" in flat or "salah" in flat):
                    for r in t.rows[1:]:  # skip header
                        if len(r) < 3:
                            continue
                        name = re.sub(r"<[^>]+>", " ", r[0]).strip()
                        begin = re.sub(r"<[^>]+>", " ", r[1]).strip()
                        jamat = re.sub(r"<[^>]+>", " ", r[2]).strip()
                        if name and jamat:
                            prayer_rows.append((name, begin, jamat))

        for prayer_label, begins, iqamah in prayer_rows:
            prayer_label = prayer_label.strip()
            begins = (begins or "").strip()
            iqamah = (iqamah or "").strip()

            prayer = parse_prayer_label(prayer_label)
            if prayer is None:
                # Also accept raw labels like "Magrib"
                pl = prayer_label.lower()
                if "magrib" in pl or "maghrib" in pl:
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
                        selector="salah table row",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )

        # Stable order by canonical prayer order for the day
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
