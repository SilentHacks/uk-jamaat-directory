from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
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
    key = "al_markaz_ul_islami_7c181174"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("almarkazulislami.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://almarkazulislami.org.uk/",
            kind=TargetKind.HTML,
        ),
    )

    # Daily tall widget (dpt plugin) with explicit Iqamah/Jammat column.
    # No multi-day date column; override extract below.
    table_keywords = ("salah", "jammat")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: "jammat",
        Prayer.DHUHR: "jammat",
        Prayer.ASR: "jammat",
        Prayer.MAGHRIB: "jammat",
        Prayer.ISHA: "jammat",
        Prayer.JUMUAH: "jammat",
    }

    def clean_cell(self, value: str) -> str:
        v = (value or "").strip()
        v = re.sub(r"<[^>]+>", " ", v)
        v = " ".join(v.split())
        return v

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()

        rows_out: list[ExtractorRow] = []
        warnings: list = []
        seen: set[tuple] = set()

        # Infer current date from any banner text, else today.
        date_text = ""
        m = re.search(
            r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2}\b",
            html,
            re.I,
        )
        if m:
            date_text = m.group(0)
        if not date_text:
            m = re.search(
                r"\b\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{2}\b",
                html,
                re.I,
            )
            if m:
                date_text = m.group(0)
        row_date = (
            parse_date_flexible(date_text, default_year=datetime.now().year) if date_text else None
        )
        if row_date is None:
            row_date = datetime.now().date()

        prayer_map = {
            "fajr": Prayer.FAJR,
            "zuhr": Prayer.DHUHR,
            "zohr": Prayer.DHUHR,
            "dhuh": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "magh": Prayer.MAGHRIB,
            "magrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
            "jumah": Prayer.JUMUAH,
            "jumuah": Prayer.JUMUAH,
            "jumma": Prayer.JUMUAH,
            "jumu": Prayer.JUMUAH,
        }

        def add_row(
            name: str, jamaat_raw: str, start_raw: str | None = None, *, session_number: int = 1
        ) -> None:
            nm = (name or "").lower()
            p = None
            for k, pr in prayer_map.items():
                if k in nm:
                    p = pr
                    break
            if p is None:
                return
            jamaat = coerce_time(jamaat_raw, prayer=p.value)
            if jamaat is None:
                warnings.append(
                    type(
                        "W",
                        (),
                        {
                            "code": "unparseable_time",
                            "message": f"{row_date} {p.value}: {jamaat_raw!r}",
                            "target_label": self.target_label,
                        },
                    )()
                )
                return
            start = coerce_time(start_raw, prayer=p.value) if start_raw else None
            key = (row_date, p.value, session_number)
            if key in seen:
                return
            seen.add(key)
            rows_out.append(
                ExtractorRow(
                    date=row_date,
                    prayer=p,
                    jamaat_time=jamaat,
                    start_time=start,
                    session_number=session_number,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label=self.target_label,
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=f"{name} | {start_raw or ''} | {jamaat_raw}",
                        selector="prayer widget row",
                    ),
                )
            )

        # Prefer <table> timetable (Salah/Time/Jammat or similar) if present
        tables = html_helpers.extract_tables(html)
        table_found = False
        for t in tables:
            flat = " ".join(" ".join(r) for r in t.rows).lower()
            if ("jammat" in flat or "iqamah" in flat) and "fajr" in flat:
                for r in t.rows:
                    cells = [self.clean_cell(c) for c in r]
                    if len(cells) < 2:
                        continue
                    joined = " ".join(cells).lower()
                    if any(
                        h in joined for h in ("salah", "salat", "time", "jammat", "iqamah")
                    ) and not any(k in joined for k in ("fajr", "zuhr", "asr")):
                        continue
                    name = cells[0]
                    start_raw = None
                    jamaat_raw = None
                    for c in cells[1:]:
                        if coerce_time(c):
                            if start_raw is None:
                                start_raw = c
                            else:
                                jamaat_raw = c
                    if not jamaat_raw:
                        for c in reversed(cells[1:]):
                            if coerce_time(c):
                                jamaat_raw = c
                                break
                    if jamaat_raw:
                        add_row(name, jamaat_raw, start_raw)
                if rows_out:
                    table_found = True
                    break

        # Also parse <ul class="prayer-times"> only if table did not yield the daily set
        if not table_found:
            ul_match = re.search(
                r'<ul[^>]*class=["\'][^"\']*prayer-times[^"\']*["\'][^>]*>(.*?)</ul>',
                html,
                re.I | re.S,
            )
            if ul_match:
                lis = re.findall(r"<li[^>]*>(.*?)</li>", ul_match.group(1), re.I | re.S)
                for li in lis:
                    spans = re.findall(r"<span[^>]*>(.*?)</span>", li, re.I | re.S)
                    if len(spans) >= 3:
                        name = self.clean_cell(spans[0])
                        start_raw = self.clean_cell(spans[1])
                        jamaat_raw = self.clean_cell(spans[2])
                        if jamaat_raw:
                            add_row(name, jamaat_raw, start_raw)
                    else:
                        txt = self.clean_cell(re.sub(r"<[^>]+>", " ", li))
                        parts = [p for p in re.split(r"\s{2,}|\s*\|\s*", txt) if p]
                        if len(parts) >= 3:
                            name = parts[0]
                            start_raw = parts[1] if len(parts) > 1 else None
                            jamaat_raw = parts[2] if len(parts) > 2 else None
                            if jamaat_raw:
                                add_row(name, jamaat_raw, start_raw)

        # Fallback: Jumuah time from banner text if not captured in rows
        if not any(r.prayer == Prayer.JUMUAH for r in rows_out):
            mj = re.search(
                r"(?:Jumah|Jumuah|Jummah)[^<]{0,100}?(?:Iqamah|Time|Jamaat)?[^<]{0,30}?(\d{1,2}:\d{2}\s*(?:am|pm)?)",
                html,
                re.I | re.S,
            )
            if mj:
                jt = coerce_time(mj.group(1), prayer="jumuah")
                if jt:
                    add_row("Jumuah", mj.group(1), None, session_number=1)

        if not rows_out:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows_out, warnings=warnings)
