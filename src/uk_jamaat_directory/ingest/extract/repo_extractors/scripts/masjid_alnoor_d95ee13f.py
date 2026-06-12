from __future__ import annotations

import re
from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_month_name
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)


def _parse_visible_date(html: str) -> date | None:
    m = re.search(
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
        html,
        re.IGNORECASE,
    )
    if not m:
        return None
    day = int(m.group(2))
    mon = parse_month_name(m.group(3))
    year = int(m.group(4))
    if mon is None:
        return None
    try:
        return date(year, mon, day)
    except ValueError:
        return None


class Extractor(BaseMosqueWebsiteExtractor):
    key = "masjid_alnoor_d95ee13f"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("alnoorcet.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://alnoorcet.co.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def __init__(self) -> None:
        super().__init__()

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()

        row_date = _parse_visible_date(html)
        if row_date is None:
            return ExtractorResult(rows=[], no_schedule_reason="no date found in page")

        # Collect jamaat times from the today widget (desktop or mobile spans pi6..pi10)
        jamaat_map: dict[Prayer, str] = {}
        for pid, prayer in (
            ("6", Prayer.FAJR),
            ("7", Prayer.DHUHR),
            ("8", Prayer.ASR),
            ("9", Prayer.MAGHRIB),
            ("10", Prayer.ISHA),
        ):
            m = re.search(rf'class="[^"]*pi{pid}[^"]*"[^>]*>([0-9:]+)</span>', html)
            if m:
                jamaat_map[prayer] = m.group(1)

        if not jamaat_map:
            # mobile layout fallback (consecutive spans)
            for pid, prayer in (
                ("6", Prayer.FAJR),
                ("7", Prayer.DHUHR),
                ("8", Prayer.ASR),
                ("9", Prayer.MAGHRIB),
                ("10", Prayer.ISHA),
            ):
                m = re.search(rf"pi{pid}[^>]*>([0-9:]+)</span>", html)
                if m:
                    jamaat_map[prayer] = m.group(1)

        if not jamaat_map:
            return ExtractorResult(rows=[], no_schedule_reason="no jamaat times found in widget")

        warnings: list = []
        rows: list[ExtractorRow] = []

        is_friday = row_date.weekday() == 4
        jummah_times: list = []
        if is_friday:
            for label in ("1st", "2nd"):
                jm = re.search(
                    rf"{label}\s*Jummah[^<]*<strong>([^<]+)</strong>", html, re.IGNORECASE
                )
                if jm:
                    jt = coerce_time(jm.group(1), prayer="dhuhr")
                    if jt:
                        jummah_times.append(jt)

        for prayer in (Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA):
            raw = jamaat_map.get(prayer)
            if not raw:
                continue
            jt = coerce_time(raw, prayer=prayer.value)
            if jt is None:
                continue
            if prayer == Prayer.DHUHR and jummah_times:
                for idx, jtt in enumerate(jummah_times, start=1):
                    rows.append(
                        ExtractorRow(
                            date=row_date,
                            prayer=Prayer.JUMUAH,
                            jamaat_time=jtt,
                            session_number=idx,
                            session_label=f"{idx}st Jumuah" if idx == 1 else f"{idx}nd Jumuah",
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"jummah{idx} {raw}",
                                selector="jummah text",
                            ),
                        )
                    )
            else:
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jt,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=raw,
                            selector=f"today-widget pi for {prayer.value}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no extractable jamaat rows")
        return ExtractorResult(rows=rows, warnings=warnings)
