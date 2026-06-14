from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
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
    key = "jamia_masjid_ibrahim_4a6516ac"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("masjidibrahim.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.masjidibrahim.org/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = extract_tables(html)
        the_table = None
        for t in tables:
            text = " ".join(" ".join(r) for r in t.rows).lower()
            if "iqama" in text or "iqamah" in text:
                the_table = t
                break
        if the_table is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no iqama timetable table found",
            )

        # extract date from title area e.g. "Jun 12, 2026"
        date_text = ""
        for row in the_table.rows[:3]:
            for cell in row:
                if re.search(
                    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+20\d{2}",
                    cell,
                    re.IGNORECASE,
                ):
                    date_text = cell
                    break
            if date_text:
                break
        row_date = parse_date_flexible(date_text, default_year=datetime.now().year)
        if row_date is None:
            row_date = datetime.now().date()

        # locate header row for columns
        adhan_idx = 1
        iqama_idx = 2
        data_start = 2
        for i, row in enumerate(the_table.rows):
            lows = [(c or "").lower() for c in row]
            if any("adhan" in c for c in lows) and any("iqama" in c for c in lows):
                try:
                    adhan_idx = lows.index(next(c for c in lows if "adhan" in c))
                    iqama_idx = lows.index(next(c for c in lows if "iqama" in c))
                except StopIteration:
                    pass
                data_start = i + 1
                break

        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []
        prayer_map = {
            "fajr": Prayer.FAJR,
            "dhuhr": Prayer.DHUHR,
            "zuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
            "ishaa": Prayer.ISHA,
        }

        for r_idx, row in enumerate(the_table.rows[data_start:], start=data_start):
            if not row or not row[0]:
                continue
            label = (row[0] or "").strip().lower().replace("'", "").replace('"', "").strip()
            time_cells = [c.strip() for c in row[1:] if c and c.strip()]
            if not time_cells:
                continue

            prayer = None
            jamaat_raw = None
            if "jumua" in label or "jumu" in label or "khutba" in label:
                prayer = Prayer.JUMUAH
                jamaat_raw = time_cells[0] if time_cells else None
            else:
                for key, pr in prayer_map.items():
                    if key in label:
                        prayer = pr
                        break
                if prayer is None:
                    continue
                if len(row) > iqama_idx and row[iqama_idx]:
                    jamaat_raw = row[iqama_idx]
                else:
                    jamaat_raw = time_cells[-1] if time_cells else None

            if not jamaat_raw:
                continue

            pkey_for_coerce = prayer.value if prayer != Prayer.JUMUAH else "jumuah"
            jt = coerce_time(jamaat_raw, prayer=pkey_for_coerce)
            if jt is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{row_date} {pkey_for_coerce}: {jamaat_raw!r}",
                        target_label="timetable",
                    )
                )
                continue

            window = PLAUSIBLE_WINDOWS.get(pkey_for_coerce)
            if window and not (window[0] <= jt <= window[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"{row_date} {pkey_for_coerce}: {jamaat_raw!r} outside plausible window",
                        target_label="timetable",
                    )
                )
                continue

            sess = 1 if prayer == Prayer.JUMUAH else 1
            rows.append(
                ExtractorRow(
                    date=row_date,
                    prayer=prayer,
                    jamaat_time=jt,
                    session_number=sess,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join(row),
                        selector=f"mi-table row {r_idx}",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
