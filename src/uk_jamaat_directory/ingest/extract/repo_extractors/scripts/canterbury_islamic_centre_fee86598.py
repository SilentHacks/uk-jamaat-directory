from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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
    key = "canterbury_islamic_centre_fee86598"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("canterburymosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://canterburymosque.co.uk/",
                kind=TargetKind.HTML,
            ),
        )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []
        today = datetime.now().date()
        row_date = today

        tables = html_helpers.extract_tables(html)
        target_table = None
        for t in tables:
            cells = [c.lower() for c in (t.header or [])]
            if any("salat" in c or "begins" in c or "jamah" in c for c in cells):
                target_table = t
                break
            for r in t.body()[:2]:
                if any(
                    "salat" in c.lower() or "begins" in c.lower() or "jamah" in c.lower() for c in r
                ):
                    target_table = t
                    break

        # extract date from header banner if present (e.g. "Canterbury, UKFriday, 12th June, 2026")
        header_blob = ""
        if target_table and target_table.header:
            header_blob = " ".join(target_table.header)
        for r in target_table.body()[:2] if target_table else []:
            header_blob += " " + " ".join(r)
        text = html_helpers.html_to_text(html)
        m = re.search(
            r"(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s*,?\s*\d{4})", header_blob + " " + text, re.IGNORECASE
        )
        if m:
            parsed = parse_date_flexible(m.group(1), default_year=today.year)
            if parsed:
                row_date = parsed

        prayer_map: dict[str, Prayer] = {
            "fajr": Prayer.FAJR,
            "zuhr": Prayer.DHUHR,
            "dhuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "magrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        if target_table:
            for r in target_table.body():
                if len(r) < 3:
                    continue
                label = (r[0] or "").strip().lower()
                begins = (r[1] or "").strip()
                jamah = (r[2] or "").strip()
                if "sunrise" in label:
                    continue
                pr: Prayer | None = None
                for k, p in prayer_map.items():
                    if k in label:
                        pr = p
                        break
                if pr is None:
                    continue
                jam_times = re.findall(r"\d{1,2}[:.]\d{2}\s*(?:am|pm)?", jamah, re.IGNORECASE)
                rawj = jam_times[0] if jam_times else jamah
                jt = coerce_time(rawj, prayer=pr.value)
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {pr.value}: {rawj!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                window = PLAUSIBLE_WINDOWS.get(pr.value)
                if window and not (window[0] <= jt <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{row_date} {pr.value}: {rawj!r} outside plausible window",
                            target_label="timetable",
                        )
                    )
                    continue
                st = coerce_time(begins, prayer=pr.value) if begins else None
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=pr,
                        jamaat_time=jt,
                        start_time=st,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join([c for c in r if c]),
                            selector="table row",
                        ),
                    )
                )
                # On Friday the Zuhr Jamah cell may list Jumuah times as range; emit JUMUAH rows
                if pr == Prayer.DHUHR and row_date.weekday() == 4 and len(jam_times) > 1:
                    for sidx, tj in enumerate(jam_times, start=1):
                        jt2 = coerce_time(tj, prayer="jumuah")
                        if jt2 is None:
                            continue
                        wj = PLAUSIBLE_WINDOWS.get("jumuah")
                        if wj and not (wj[0] <= jt2 <= wj[1]):
                            continue
                        rows.append(
                            ExtractorRow(
                                date=row_date,
                                prayer=Prayer.JUMUAH,
                                jamaat_time=jt2,
                                session_number=sidx,
                                timezone=ctx.timezone,
                                evidence=ctx.evidence(
                                    target_label="timetable",
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    raw_text=tj,
                                    selector=f"jumuah session {sidx}",
                                ),
                            )
                        )

        if not rows:
            # fallback: regex over text for daily prayer Jamah times (robust to layout changes)
            for label, pr in [
                ("Fajr", Prayer.FAJR),
                ("Zuhr", Prayer.DHUHR),
                ("Dhuhr", Prayer.DHUHR),
                ("Asr", Prayer.ASR),
                ("Magrib", Prayer.MAGHRIB),
                ("Maghrib", Prayer.MAGHRIB),
                ("Isha", Prayer.ISHA),
            ]:
                m = re.search(
                    rf"{re.escape(label)}\b[^0-9]*?(\d{{1,2}}[:.]\d{{2}}(?:\s*[ap]m)?)[^0-9]*?(\d{{1,2}}[:.]\d{{2}}(?:\s*[ap]m)?)",
                    text,
                    re.IGNORECASE,
                )
                if not m:
                    continue
                rawj = m.group(2).strip()
                jt = coerce_time(rawj, prayer=pr.value)
                if jt is None:
                    continue
                window = PLAUSIBLE_WINDOWS.get(pr.value)
                if window and not (window[0] <= jt <= window[1]):
                    continue
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=pr,
                        jamaat_time=jt,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=rawj,
                            selector=f"text {label}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
