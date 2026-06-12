from datetime import datetime
import re

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractorResult,
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
    key = "ely_islamic_centre_80e1b2fa"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("elyislamiccentre.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://prayers.elyislamiccentre.org/mobile-screen/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("start", "jama")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "zuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
        Prayer.JUMUAH: "jumuah",
    }

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        prayer_table = None
        for t in tables:
            htext = " ".join(t.header).lower()
            if "start" in htext and ("jama" in htext or "iqam" in htext):
                prayer_table = t
                break
        if prayer_table is None:
            for t in tables:
                joined = " ".join(" ".join(r) for r in t.rows).lower()
                if "fajr" in joined and ("jama" in joined or "dpt_jamah" in joined):
                    prayer_table = t
                    break
        if prayer_table is None:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")
        date_text = ""
        m = re.search(r'id=["\']dsDate["\'][^>]*>([^<]+)<', html, re.IGNORECASE)
        if m:
            date_text = m.group(1).strip()
        if not date_text:
            m = re.search(
                r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[^\d]*\d{1,2}[^<]*\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b",
                html,
                re.IGNORECASE,
            )
            if m:
                date_text = m.group(0)
        if not date_text:
            date_text = datetime.now().strftime("%d %B %Y")
        parsed = parse_date_flexible(date_text, default_year=datetime.now().year)
        row_date = parsed or datetime.now().date()
        dstr = f"{row_date.day}/{row_date.month}/{row_date.year}"
        jam_map: dict[Prayer, str] = {}
        for row in prayer_table.rows:
            if not row:
                continue
            label = (row[0] or "").strip()
            pr = parse_prayer_label(label)
            if pr is None:
                for c in row:
                    pr = parse_prayer_label(c)
                    if pr:
                        break
            if pr is None:
                continue
            raw_j = ""
            for c in reversed(row):
                if c and any(ch.isdigit() for ch in c):
                    raw_j = c.strip()
                    break
            if raw_j:
                jam_map[pr] = raw_j
        if not jam_map:
            return ExtractorResult(rows=[], no_schedule_reason="no jamaat times found")
        logical_header = ["date", "fajr", "zuhr", "asr", "maghrib", "isha", "jumuah"]
        data_row = [dstr]
        for p in (
            Prayer.FAJR,
            Prayer.DHUHR,
            Prayer.ASR,
            Prayer.MAGHRIB,
            Prayer.ISHA,
            Prayer.JUMUAH,
        ):
            data_row.append(jam_map.get(p, ""))
        effective = html_helpers.Table([logical_header, data_row])
        return self._extract_from_table(ctx, effective)
