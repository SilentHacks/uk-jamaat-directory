from __future__ import annotations

import datetime
import re

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
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
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    BaseMosqueWebsiteExtractor,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "madina_masjid___islamic_centre_c5414996"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("mmic.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://mmic.org.uk/prayer-times",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    PRAYER_ORDER = [
        ("Fajr", Prayer.FAJR),
        ("Dhuhr", Prayer.DHUHR),
        ("Asr", Prayer.ASR),
        ("Maghrib", Prayer.MAGHRIB),
        ("Isha", Prayer.ISHA),
    ]

    def _extract_days(self, html: str) -> list[int]:
        # Collect every day number that appears inside any date-list ul's li span.
        # Skip panes with empty uls; the real month days live in the slick carousel slides.
        days: list[int] = []
        for m in re.finditer(
            r'<div[^>]*class="date-list"[^>]*>.*?<ul[^>]*>(.*?)</ul>',
            html,
            re.I | re.S,
        ):
            inner = m.group(1)
            for d in re.findall(r"<li[^>]*>\s*<span>\s*(\d{1,2})\s*</span>", inner):
                try:
                    val = int(d)
                    if 1 <= val <= 31:
                        days.append(val)
                except ValueError:
                    pass
        if not days:
            # Very broad fallback: any span that is a bare day number near "Date" or in a listing-wrapper near a date-list
            for d in re.findall(r"<span>\s*(\d{1,2})\s*</span>", html):
                try:
                    val = int(d)
                    if 1 <= val <= 31:
                        days.append(val)
                except ValueError:
                    pass
        # de-duplicate while preserving first-seen order, take at most one month
        seen: set[int] = set()
        uniq: list[int] = []
        for d in days:
            if d not in seen:
                seen.add(d)
                uniq.append(d)
        return uniq[:31]

    def _collect_all_jamaah_lists(self, html: str) -> list[list[str]]:
        """Return every 28-31 entry jamaah list found in any timing-list ul (second time span per li)."""
        lists: list[list[str]] = []
        for m in re.finditer(
            r'<div[^>]*class="timing-list"[^>]*>.*?<ul[^>]*>(.*?)</ul>\s*</div>\s*</div>\s*</div>',
            html,
            re.I | re.S,
        ):
            ul = m.group(1)
            jamaahs: list[str] = []
            for li in re.findall(r"<li[^>]*>(.*?)</li>", ul, re.I | re.S):
                spans = re.findall(
                    r'<div[^>]*class="timing-text"[^>]*>\s*<span>([^<]+)</span>',
                    li,
                )
                if len(spans) >= 2:
                    jamaahs.append(spans[1].strip())
            if 28 <= len(jamaahs) <= 31:
                lists.append(jamaahs)
        # de-dupe identical lists
        seen: set[tuple[str, ...]] = set()
        uniq: list[list[str]] = []
        for j in lists:
            key = tuple(j)
            if key not in seen:
                seen.add(key)
                uniq.append(j)
        return uniq

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        now = datetime.datetime.now()
        year = now.year
        month = now.month

        days = self._extract_days(html)
        if not days:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_days",
                        message="no day list found in rendered timetable",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no day list found",
            )

        jamaah_lists = self._collect_all_jamaah_lists(html)
        if len(jamaah_lists) < 5:
            # Not enough distinct monthly jamaah lists; the carousel may not have populated all 5.
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_jamaah_lists",
                        message=f"only {len(jamaah_lists)} monthly jamaah lists found (need 5)",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no jamaah lists found",
            )

        # Map the 5 lists to prayers by the known signatures from the site (first jamaah time).
        # Observed: Fajr~4:00am, Dhuhr~1:45pm, Asr~8:00pm, Maghrib~9:3xpm, Isha~11:00pm
        sig_to_prayer: dict[str, Prayer] = {}
        prayer_to_list: dict[Prayer, list[str]] = {}
        for lst in jamaah_lists:
            sig = lst[0] if lst else ""
            prayer = None
            if "am" in sig.lower() or sig.lower().startswith("4:") or sig.lower().startswith("2:"):
                prayer = Prayer.FAJR
            elif "pm" in sig.lower():
                if sig.lower().startswith("1:"):
                    prayer = Prayer.DHUHR
                elif sig.lower().startswith("8:"):
                    prayer = Prayer.ASR
                elif sig.lower().startswith("9:") or sig.lower().startswith("10:"):
                    prayer = Prayer.MAGHRIB
                elif sig.lower().startswith("11:"):
                    prayer = Prayer.ISHA
            if prayer and prayer not in prayer_to_list:
                prayer_to_list[prayer] = lst

        # If signature mapping left some missing, fall back to order of appearance in DOM for the first 5 lists.
        if len(prayer_to_list) < 5:
            for (label, prayer), lst in zip(self.PRAYER_ORDER, jamaah_lists):
                if prayer not in prayer_to_list:
                    prayer_to_list[prayer] = lst

        for label, prayer in self.PRAYER_ORDER:
            jamaahs = prayer_to_list.get(prayer, [])
            if not jamaahs:
                warnings.append(
                    ExtractorWarning(
                        code="no_jamaah_list",
                        message=f"no jamaah list for {label}",
                        target_label="timetable",
                    )
                )
                continue
            n = min(len(days), len(jamaahs))
            for i in range(n):
                d = days[i]
                try:
                    row_date = datetime.date(year, month, d)
                except ValueError:
                    continue
                jam_raw = jamaahs[i]
                jamaat = coerce_time(jam_raw, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {label}: {jam_raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        start_time=None,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{d} | {jam_raw}",
                            selector=f"{label} day {d}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable jamaat rows from rendered lists",
            )
        return ExtractorResult(rows=rows, warnings=warnings)
