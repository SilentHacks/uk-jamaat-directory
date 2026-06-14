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
    key = "harlow_islamic_centre_8e905d13"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("harlowislamiccentre.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://harlowislamiccentre.org.uk/prayers-timetable/",
            kind=TargetKind.HTML,
        ),
    )

    # Daily tall/wide table served by the daily-prayer-time plugin.
    # Explicit Iqamah (Jamaat) column present; we target the HTML page.
    table_keywords = ("prayer", "iqamah")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: "iqamah",
        Prayer.DHUHR: "iqamah",
        Prayer.ASR: "iqamah",
        Prayer.MAGHRIB: "iqamah",
        Prayer.ISHA: "iqamah",
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

        # Find the dptTimetable(s) that contain explicit Iqamah/Jamah times.
        tables = html_helpers.extract_tables(html)
        timetable = None
        for t in tables:
            joined = " ".join(" ".join(row) for row in t.rows).lower()
            if "iqamah" in joined or "jamah" in joined:
                if "fajr" in joined:
                    timetable = t
                    break
        if timetable is None:
            for t in tables:
                h = [self.clean_cell(c).lower() for c in t.header]
                if any("iqamah" in c or "jamah" in c for c in h) and any(
                    "begins" in c or "prayer" in c for c in h
                ):
                    timetable = t
                    break
        if timetable is None:
            return ExtractorResult(
                rows=[],
                warnings=[],
                no_schedule_reason="timetable table not found",
            )

        # Parse current date from header banner, e.g. "12 June 2026".
        date_text = ""
        for row in timetable.rows:
            for cell in row:
                if re.search(
                    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b",
                    cell,
                    re.I,
                ):
                    date_text = cell
                    break
            if date_text:
                break
        if not date_text:
            m = re.search(
                r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b",
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
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        rows_out: list[ExtractorRow] = []
        warnings: list = []

        for r in timetable.rows:
            cells = [self.clean_cell(c) for c in r]
            if not cells:
                continue
            name = cells[0].lower()
            p = None
            for key, pr in prayer_map.items():
                if key in name:
                    p = pr
                    break
            if p is None:
                continue
            # Structure: [name, begins, iqamah] or similar; pick last parsable time as jamaat.
            jamaat_raw = ""
            for c in reversed(cells[1:]):
                if coerce_time(c, prayer=p.value):
                    jamaat_raw = c
                    break
            if not jamaat_raw:
                continue
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
                continue
            rows_out.append(
                ExtractorRow(
                    date=row_date,
                    prayer=p,
                    jamaat_time=jamaat,
                    start_time=None,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label=self.target_label,
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join(cells),
                        selector="dptTimetable row",
                    ),
                )
            )

        if not rows_out:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows_out, warnings=warnings)
