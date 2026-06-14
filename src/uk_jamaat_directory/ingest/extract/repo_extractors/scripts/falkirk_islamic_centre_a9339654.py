from datetime import datetime
import re

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables, html_to_text
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
    key = "falkirk_islamic_centre_a9339654"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("falkirkcentralmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://falkirkcentralmosque.com/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = extract_tables(html)
        full_text = html_to_text(html)
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        # Parse the date shown on the page (e.g. "12 June 2026")
        parsed_date = None
        date_m = re.search(
            r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{4})",
            full_text,
            re.I,
        )
        if date_m:
            parsed_date = parse_date_flexible(date_m.group(1), default_year=datetime.now().year)
        if parsed_date is None:
            for t in tables:
                for r in t.rows:
                    for c in r:
                        d = parse_date_flexible(c, default_year=datetime.now().year)
                        if d:
                            parsed_date = d
                            break
                    if parsed_date:
                        break
                if parsed_date:
                    break
        if parsed_date is None:
            parsed_date = datetime.now().date()

        # Locate the prayer table (header contains Prayer + Iqamah/Adhan)
        prayer_table = None
        for t in tables:
            h = " ".join(t.header).lower()
            if "prayer" in h and ("iqamah" in h or "iqama" in h or "adhan" in h):
                prayer_table = t
                break
        if prayer_table is None:
            for t in tables:
                if len(t.rows) >= 2:
                    r1 = " ".join(t.rows[1]).lower()
                    if "prayer" in r1 and ("iqamah" in r1 or "iqama" in r1 or "adhan" in r1):
                        prayer_table = t
                        break

        if prayer_table:
            header = [c.strip() for c in prayer_table.header]
            body_start = 1
            hlower = [c.lower() for c in header]
            if not any("prayer" in x for x in hlower):
                if len(prayer_table.rows) > 1:
                    header = [c.strip() for c in prayer_table.rows[1]]
                    body_start = 2
            prayer_idx = None
            iqamah_idx = None
            for i, h in enumerate(header):
                hl = h.lower()
                if prayer_idx is None and "prayer" in hl:
                    prayer_idx = i
                if iqamah_idx is None and ("iqamah" in hl or "iqama" in hl):
                    iqamah_idx = i
            if prayer_idx is None:
                prayer_idx = 0
            if iqamah_idx is None:
                iqamah_idx = 2

            prayer_map = {
                "fajr": Prayer.FAJR,
                "zuhr": Prayer.DHUHR,
                "asr": Prayer.ASR,
                "maghrib": Prayer.MAGHRIB,
                "isha": Prayer.ISHA,
            }
            for rnum, row in enumerate(prayer_table.rows[body_start:], start=body_start + 1):
                if len(row) <= max(prayer_idx, iqamah_idx):
                    continue
                p_name = row[prayer_idx].strip().lower()
                if p_name not in prayer_map:
                    continue
                prayer = prayer_map[p_name]
                raw_j = (row[iqamah_idx] if iqamah_idx < len(row) else "").strip()
                if not raw_j:
                    continue
                jamaat = coerce_time(raw_j, prayer=prayer.value)
                if jamaat is None:
                    continue
                win = PLAUSIBLE_WINDOWS.get(prayer.value)
                if win and not (win[0] <= jamaat <= win[1]):
                    continue
                rows.append(
                    ExtractorRow(
                        date=parsed_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(c.strip() for c in row),
                            selector=f"table row {rnum}",
                        ),
                    )
                )

        # Jumuah sessions from page text (1st/2nd Iqamah near Jumuah)
        j1 = j2 = None
        m1 = re.search(
            r"(?:1st|first)\s*(?:Iqamah|Iqama|Jumuah|Jummah|Jumu'ah)\s*[:\s]*(\d{1,2}[:.]\d{2})",
            full_text,
            re.I,
        )
        if m1:
            j1 = coerce_time(m1.group(1), prayer="jumuah")
        m2 = re.search(
            r"(?:2nd|second)\s*(?:Iqamah|Iqama|Jumuah|Jummah|Jumu'ah)\s*[:\s]*(\d{1,2}[:.]\d{2})",
            full_text,
            re.I,
        )
        if m2:
            j2 = coerce_time(m2.group(1), prayer="jumuah")
        if not (j1 and j2):
            jm = re.search(
                r"Jumu[^<]{0,60}?(\d{1,2}:\d{2}).{0,30}?(\d{1,2}:\d{2})", full_text, re.I
            )
            if jm:
                if j1 is None:
                    j1 = coerce_time(jm.group(1), prayer="jumuah")
                if j2 is None:
                    j2 = coerce_time(jm.group(2), prayer="jumuah")

        if j1:
            rows.append(
                ExtractorRow(
                    date=parsed_date,
                    prayer=Prayer.JUMUAH,
                    jamaat_time=j1,
                    session_number=1,
                    session_label="1st Iqamah",
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text="Jumuah 1st",
                        selector="jumuah text",
                    ),
                )
            )
        if j2:
            rows.append(
                ExtractorRow(
                    date=parsed_date,
                    prayer=Prayer.JUMUAH,
                    jamaat_time=j2,
                    session_number=2,
                    session_label="2nd Iqamah",
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text="Jumuah 2nd",
                        selector="jumuah text",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
