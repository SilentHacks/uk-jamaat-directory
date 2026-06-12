from __future__ import annotations

import re
from datetime import datetime

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
    key = "kettering_muslim_association_bad6943b"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("ketteringmosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://ketteringmosque.co.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        text = html_to_text(html)
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        # Parse date from header e.g. "Friday, June 12 Prayer Times"
        year = datetime.now().year
        parsed_date = None
        dm = re.search(
            r"(?i)(?:[A-Za-z]+day,?\s*)?(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})",
            text,
        )
        if dm:
            mon, day = dm.group(1), dm.group(2)
            parsed_date = parse_date_flexible(f"{mon} {day}", default_year=year)
        if parsed_date is None:
            parsed_date = datetime.now().date()

        tables = extract_tables(html)

        # Prayer table with Start/Jamaat columns (today only)
        prayer_table = None
        for t in tables:
            hblob = " ".join(str(c).lower() for c in t.header)
            rblob = " ".join(" ".join(str(c).lower() for c in r) for r in t.rows)
            if "jamaat" in (hblob + " " + rblob) and ("fajr" in rblob or "prayer" in hblob.lower()):
                prayer_table = t
                break

        if prayer_table:
            header_lower = [str(c).strip().lower() for c in prayer_table.header]

            def find_col(kws):
                for i, h in enumerate(header_lower):
                    if any(k in h for k in kws):
                        return i
                return None

            idx_label = find_col(["prayer", "salah"]) or 0
            idx_start = find_col(["start"])
            idx_jamaat = find_col(["jamaat", "iqamah"])

            for rnum, row in enumerate(prayer_table.rows):
                if rnum == 0 and any("prayer" in str(c).lower() for c in row):
                    continue
                if len(row) < 3:
                    continue
                label = (
                    str(
                        row[idx_label] if idx_label is not None and idx_label < len(row) else row[0]
                    )
                    .strip()
                    .lower()
                )
                raw_start = str(
                    row[idx_start]
                    if idx_start is not None and idx_start < len(row)
                    else (row[1] if len(row) > 1 else "")
                ).strip()
                raw_j = str(
                    row[idx_jamaat]
                    if idx_jamaat is not None and idx_jamaat < len(row)
                    else (row[2] if len(row) > 2 else "")
                ).strip()
                pkey = label
                if pkey == "zuhr":
                    prayer = Prayer.DHUHR
                elif pkey in ("magrib", "maghrib"):
                    prayer = Prayer.MAGHRIB
                else:
                    prayer = {
                        "fajr": Prayer.FAJR,
                        "dhuhr": Prayer.DHUHR,
                        "asr": Prayer.ASR,
                        "maghrib": Prayer.MAGHRIB,
                        "isha": Prayer.ISHA,
                    }.get(pkey)
                if prayer is None or prayer == Prayer.JUMUAH:
                    continue
                jamaat = coerce_time(raw_j, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{parsed_date} {label}: {raw_j!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                win = PLAUSIBLE_WINDOWS.get(prayer.value)
                if win and not (win[0] <= jamaat <= win[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{parsed_date} {prayer.value}: {raw_j!r} outside plausible window",
                            target_label="timetable",
                        )
                    )
                    continue
                start_t = coerce_time(raw_start, prayer=prayer.value) if raw_start else None
                rows.append(
                    ExtractorRow(
                        date=parsed_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        start_time=start_t,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(str(x) for x in row),
                            selector=f"table row {rnum}",
                        ),
                    )
                )

        # Jumuah sessions (static on page, emit for the displayed date)
        jumuah_table = None
        for t in tables:
            blob = " ".join(" ".join(str(c).lower() for c in r) for r in t.rows)
            if "jumuah" in blob or ("1st" in blob and "jamaat" in blob):
                jumuah_table = t
                break
        if jumuah_table:
            sess = 0
            for rnum, row in enumerate(jumuah_table.rows):
                if not row:
                    continue
                cell_text = " ".join(str(c) for c in row)
                if "jumuah" in cell_text.lower() and "jamaat" in cell_text.lower():
                    continue
                tm = re.search(r"(\d{1,2}[:.]\d{2}\s*(?:am|pm)?)", cell_text, re.IGNORECASE)
                if not tm:
                    continue
                raw = tm.group(1).replace(".", ":").strip()
                jt = coerce_time(raw, prayer="jumuah")
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{parsed_date} jumuah: {raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                win = PLAUSIBLE_WINDOWS.get("jumuah")
                if win and not (win[0] <= jt <= win[1]):
                    continue
                sess += 1
                rows.append(
                    ExtractorRow(
                        date=parsed_date,
                        prayer=Prayer.JUMUAH,
                        jamaat_time=jt,
                        session_number=sess,
                        session_label=str(row[0]).strip() if row else None,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=cell_text,
                            selector=f"jumuah table row {rnum}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
