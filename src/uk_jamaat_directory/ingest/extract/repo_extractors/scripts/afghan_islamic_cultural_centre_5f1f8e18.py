from __future__ import annotations

import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_day_of_month
from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS, coerce_time
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

MONTH_SEGMENTS: dict[int, str] = {
    1: "N01_january",
    2: "N02_February",
    3: "N03_March",
    4: "N04_April",
    5: "N05_may",
    6: "N06_June",
    7: "N07_July",
    8: "N08_August",
    9: "N09_september",
    10: "N10_October",
    11: "N11_November",
    12: "N12_December",
}


class Extractor(BaseMosqueWebsiteExtractor):
    key = "afghan_islamic_cultural_centre_5f1f8e18"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("afghanicc.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        seg = MONTH_SEGMENTS.get(now.month, "N06_June")
        url = f"http://afghanicc.com/images/namaztimes/{seg}.pdf"
        self._targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        try:
            doc = pdf_helpers.open_pdf(artifact.body)
            full_text = "\n".join((p.get_text() or "") for p in doc)
            doc.close()
        except Exception:
            return ExtractorResult(rows=[], no_schedule_reason="failed to open PDF")

        tokens = [t.strip() for t in re.split(r"\s+", full_text) if t.strip()]
        day_week_re = re.compile(r"^(\d{1,2})\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)$", re.IGNORECASE)
        rows: list[ExtractorRow] = []
        i = 0
        n = len(tokens)
        year = datetime.now().year
        month = datetime.now().month
        try:
            m = re.search(r"/N(\d{2})_", artifact.target_url)
            if m:
                inferred = int(m.group(1))
                if 1 <= inferred <= 12:
                    month = inferred
        except Exception:
            pass

        while i < n:
            tok = tokens[i]
            m = day_week_re.match(tok)
            if m:
                day = int(m.group(1))
                i += 1
            else:
                dm = parse_day_of_month(tok)
                if (
                    dm is not None
                    and i + 1 < n
                    and tokens[i + 1][:3].lower()
                    in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
                ):
                    day = dm
                    i += 2
                else:
                    i += 1
                    continue
            try:
                row_date = date(year, month, day)
            except ValueError:
                continue
            times: list[str] = []
            while i < n and len(times) < 12:
                t = tokens[i]
                if ":" in t and re.match(r"^\d{1,2}:\d{2}(?::\d{2})?$", t):
                    times.append(t)
                    i += 1
                elif day_week_re.match(t) or (
                    parse_day_of_month(t) is not None
                    and i + 1 < n
                    and tokens[i + 1][:3].lower()
                    in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
                ):
                    break
                else:
                    i += 1
            if len(times) < 8:
                continue
            jamaat_map = {
                Prayer.FAJR: 1,
                Prayer.DHUHR: 4,
                Prayer.ASR: 6,
                Prayer.MAGHRIB: 8,
                Prayer.ISHA: 10,
            }
            for prayer, t_idx in jamaat_map.items():
                if t_idx >= len(times):
                    continue
                raw = times[t_idx]
                jt = coerce_time(raw, prayer=prayer.value)
                if jt is None:
                    continue
                window = PLAUSIBLE_WINDOWS.get(prayer.value)
                if window and not (window[0] <= jt <= window[1]):
                    continue
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jt,
                        start_time=None,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=raw,
                            selector=f"pdf token row for {row_date}",
                        ),
                    )
                )
            if len(times) > 11:
                jraw = times[11]
                jt = coerce_time(jraw, prayer=Prayer.JUMUAH.value)
                if jt:
                    win = PLAUSIBLE_WINDOWS.get(Prayer.JUMUAH.value)
                    if not win or (win[0] <= jt <= win[1]):
                        rows.append(
                            ExtractorRow(
                                date=row_date,
                                prayer=Prayer.JUMUAH,
                                jamaat_time=jt,
                                start_time=None,
                                session_number=1,
                                timezone=ctx.timezone,
                                evidence=ctx.evidence(
                                    target_label="timetable",
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    raw_text=jraw,
                                    selector=f"pdf jumuah for {row_date}",
                                ),
                            )
                        )

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no extractable rows")
        return ExtractorResult(rows=rows)
