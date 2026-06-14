from __future__ import annotations

import re
from datetime import datetime, timedelta

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
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
    key = "ayrshire_central_masjid_5ddc2394"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("ayrshirecentralmosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://ayrshirecentralmosque.org.uk/daily-prayers-and-jummah/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)

        prayer_table = None
        for t in tables:
            h = " ".join(t.header).lower()
            if "salah" in h and ("jammat" in h or "jamaat" in h or "iqamah" in h):
                prayer_table = t
                break
        if prayer_table is None:
            for t in tables:
                blob = " ".join(" ".join(str(c) for c in r) for r in t.rows).lower()
                if "fajr" in blob and ("jammat" in blob or "jamaat" in blob):
                    prayer_table = t
                    break

        rows_out: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        today = datetime.now().date()

        if prayer_table:
            for rnum, row in enumerate(prayer_table.rows, start=1):
                if not row:
                    continue
                if rnum == 1 and any("salah" in str(c).lower() for c in row):
                    continue
                if len(row) < 3:
                    continue
                label = str(row[0]).strip()
                raw_j = str(row[2]).strip() if len(row) > 2 else ""
                if not raw_j or not label:
                    continue
                prayer = parse_prayer_label(label)
                if prayer is None or prayer == Prayer.JUMUAH:
                    continue
                jt = coerce_time(raw_j, prayer=prayer.value)
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{today} {prayer.value}: {raw_j!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                rows_out.append(
                    ExtractorRow(
                        date=today,
                        prayer=prayer,
                        jamaat_time=jt,
                        start_time=None,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(str(c) for c in row),
                            selector=f"table row {rnum}",
                        ),
                    )
                )

        # Jummah / Jumuah Iqamah from dedicated text on the page (e.g. "<b>Iqamah</b>: 1:15 PM")
        jumuah_time = None
        m = re.search(
            r"(?i)(?:Jummah|Jumuah)[^<]{0,100}?(?:Iqamah|Jammat)[^<]{0,30}?(\d{1,2}[:.]\d{2}\s*(?:AM|PM)?)",
            html,
        )
        if not m:
            m = re.search(
                r"(?i)iqamah[^<]{0,20}?(\d{1,2}:\d{2}\s*(?:AM|PM)?)",
                html,
            )
        if m:
            raw = m.group(1).replace(".", ":").strip()
            jumuah_time = coerce_time(raw, prayer="jumuah")
            if jumuah_time is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"jumuah: {raw!r}",
                        target_label="timetable",
                    )
                )
        if jumuah_time:
            wd = today.weekday()
            if wd == 4:
                j_date = today
            else:
                days_ahead = (4 - wd) % 7
                j_date = today + timedelta(days=days_ahead)
            rows_out.append(
                ExtractorRow(
                    date=j_date,
                    prayer=Prayer.JUMUAH,
                    jamaat_time=jumuah_time,
                    session_number=1,
                    session_label="Jummah",
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text="Jummah Iqamah",
                        selector="jummah text",
                    ),
                )
            )

        if not rows_out:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows_out, warnings=warnings)
