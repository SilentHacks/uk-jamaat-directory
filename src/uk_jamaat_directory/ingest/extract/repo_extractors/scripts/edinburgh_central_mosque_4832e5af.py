import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.relative import add_minutes
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractorResult,
    ExtractorRow,
    ExtractorWarning,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    TableTimetableExtractor,
)


class Extractor(TableTimetableExtractor):
    key = "edinburgh_central_mosque_4832e5af"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("edmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://edmosque.org/about-the-mosque/prayer-times/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("fajr", "zuhr")

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()

        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        # Month/year from the page H2 (e.g. "June 2026"); fall back to now()
        year = datetime.now().year
        month = datetime.now().month
        m = re.search(r"<h2[^>]*>\s*([A-Za-z]+)\s+(20\d{2})\s*</h2>", html, re.I)
        if m:
            mon_map = {
                "jan": 1,
                "feb": 2,
                "mar": 3,
                "apr": 4,
                "may": 5,
                "jun": 6,
                "jul": 7,
                "aug": 8,
                "sep": 9,
                "oct": 10,
                "nov": 11,
                "dec": 12,
            }
            mon_name = m.group(1).lower()[:3]
            month = mon_map.get(mon_name, month)
            year = int(m.group(2))

        # Split into <tr> chunks (robust to missing close tags)
        tm = re.search(r"<table[^>]*>.*?</table>", html, re.DOTALL | re.IGNORECASE)
        tbl = tm.group(0) if tm else html
        parts = re.split(r"<tr\b[^>]*>", tbl, flags=re.IGNORECASE)[1:]

        # Jama'ah periods: (start_day, end_day, [f,z,a,m,i] jamaat strings)
        periods: list[tuple[int, int, list[str]]] = []
        # Daily adhan rows: day -> (weekday, [f,z,a,m,i] adhan strings)
        day_adhan: dict[int, tuple[str, list[str]]] = {}

        for chunk in parts:
            chunk = re.split(r"</tr|<tr\b", chunk, flags=re.I)[0]
            txt = html_helpers.strip_tags(chunk)
            txt = html_helpers.normalize_whitespace(txt)
            if not txt:
                continue
            if re.search(r"Jama", txt, re.I):
                jm = re.search(r"\((\d{1,2})\D+(\d{1,2})", txt)
                if jm:
                    sd, ed = int(jm.group(1)), int(jm.group(2))
                    times = re.findall(r"(\d{1,2}:\d{2}|\+\d+)", txt)
                    if len(times) >= 5:
                        periods.append((sd, ed, times[:5]))
                continue
            dm = re.match(
                r"^(\d{1,2})\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$",
                txt,
                re.I,
            )
            if dm:
                d = int(dm.group(1))
                wd = dm.group(2)
                adh = [dm.group(i) for i in range(3, 8)]
                day_adhan[d] = (wd, adh)

        if not day_adhan:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no day rows found",
            )

        # Map day -> current jamaat list for the period
        day_jamaat: dict[int, list[str]] = {}
        for sd, ed, j5 in periods:
            for d in range(sd, ed + 1):
                day_jamaat[d] = j5

        prayers = [Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA]
        prayer_keys = ["fajr", "dhuhr", "asr", "maghrib", "isha"]

        for d in sorted(day_adhan.keys()):
            wd, adh_raw = day_adhan[d]
            j5 = day_jamaat.get(d, [""] * 5)
            is_fri = wd.lower() == "friday"
            try:
                row_date = date(year, month, d)
            except ValueError:
                continue

            for i, (prayer, pkey) in enumerate(zip(prayers, prayer_keys)):
                ad_raw = adh_raw[i] if i < len(adh_raw) else ""
                j_raw = j5[i] if i < len(j5) else ""
                at = coerce_time(ad_raw, prayer=pkey) if ad_raw else None

                jt = None
                if j_raw:
                    if j_raw.startswith("+"):
                        try:
                            off = int(j_raw[1:])
                            if at is not None:
                                jt = add_minutes(at, off)
                        except Exception:
                            pass
                    else:
                        ck = "jumuah" if (is_fri and prayer is Prayer.DHUHR) else pkey
                        jt = coerce_time(j_raw, prayer=ck)

                if jt is None:
                    # no jamaat for this cell; skip (base would also drop empty)
                    continue

                # plausible window using adhan key for non-jumuah, or jumuah for friday zuhr
                win_key = "jumuah" if (is_fri and prayer is Prayer.DHUHR) else pkey
                window = None
                from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS

                window = PLAUSIBLE_WINDOWS.get(win_key)
                if window and not (window[0] <= jt <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{row_date} {win_key}: {j_raw!r} outside plausible window",
                            target_label=self.target_label,
                        )
                    )
                    continue

                pr_for_row = Prayer.JUMUAH if (is_fri and prayer is Prayer.DHUHR) else prayer
                sess = 1 if pr_for_row is Prayer.JUMUAH else 1

                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=pr_for_row,
                        jamaat_time=jt,
                        start_time=at if pr_for_row is not Prayer.JUMUAH else None,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label=self.target_label,
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{d} {wd} | {pkey} adhan={ad_raw} jamaat={j_raw}",
                            selector=f"table row day {d}",
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
