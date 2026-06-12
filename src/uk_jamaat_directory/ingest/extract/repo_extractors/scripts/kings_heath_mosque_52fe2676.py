from __future__ import annotations

import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_month_name
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
    key = "kings_heath_mosque_52fe2676"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("kingsheathmosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        y = now.year
        m = now.month
        mname = now.strftime("%B")
        url = (
            f"https://kingsheathmosque.org.uk/onewebmedia/time%20tables/{y}/{m:02d}_{mname}_{y}.pdf"
        )
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
        text = pdf_helpers.extract_text(artifact.body) or ""
        if not text.strip():
            return ExtractorResult(rows=[], no_schedule_reason="failed to extract text from PDF")

        # Derive year/month from target URL (or PDF header text) so we do not hardcode dates.
        target_url = getattr(artifact, "target_url", "") or ""
        year = datetime.now().year
        month = datetime.now().month
        m = re.search(r"/(20\d{2})/(\d{2})_([A-Za-z]+)_(20\d{2})\.pdf", target_url)
        if m:
            year = int(m.group(1))
            mon_name = m.group(3)
            mm = parse_month_name(mon_name)
            if mm:
                month = mm
        if month == datetime.now().month and year == datetime.now().year:
            # fallback: header text e.g. "JUNE 2026"
            m2 = re.search(
                r"\b(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+(20\d{2})\b",
                text,
                re.IGNORECASE,
            )
            if m2:
                mm = parse_month_name(m2.group(1))
                if mm:
                    month = mm
                year = int(m2.group(2))

        # Parse day blocks. get_text() typically emits:
        # MON
        # 15
        # 2.32
        # 2.42
        # ...
        # We look for a weekday line, then the next 1-2 lines for civil DOM (1-31),
        # then collect subsequent time-like tokens until the next weekday.
        weekday_re = re.compile(r"^(MON|TUE|WED|THU|FRI|SAT|SUN)$", re.IGNORECASE)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        seen_dom: set[int] = set()
        i = 0
        while i < len(lines):
            ln = lines[i]
            if not weekday_re.match(ln):
                i += 1
                continue
            dom = None
            for j in range(i + 1, min(i + 4, len(lines))):
                if re.match(r"^\d{1,2}$", lines[j]):
                    dval = int(lines[j])
                    if 1 <= dval <= 31:
                        dom = dval
                        break
            if dom is None:
                i += 1
                continue
            if dom in seen_dom:
                # duplicate listing (e.g. right-hand DATE column); skip
                i += 1
                continue
            # collect time tokens following this dom until next weekday or limit
            times: list[str] = []
            k = i + 2 if dom is not None else i + 1
            while k < len(lines) and k < i + 25:
                if weekday_re.match(lines[k]):
                    break
                for t in re.findall(r"\d{1,2}[.:]\d{2}", lines[k]):
                    times.append(t)
                k += 1
            if len(times) < 11:
                i = k
                continue
            try:
                row_date = date(year, month, dom)
            except ValueError:
                i = k
                continue
            seen_dom.add(dom)

            # indices in times (0-based) for JAMAAT columns, derived from layout:
            # 0:f-start, 1:f-jama, 2:sunrise-ish, 3:?, 4:z-start, 5:z-jama,
            # 6:asr-start, 7:asr-jama, 8:maghrib, 9:isha-start, 10:isha-jama
            fj = coerce_time(times[1].replace(":", "."), prayer="fajr")
            zj = coerce_time(times[5].replace(":", "."), prayer="dhuhr")
            aj = coerce_time(times[7].replace(":", "."), prayer="asr")
            mj = coerce_time(times[8].replace(":", "."), prayer="maghrib")
            ij = coerce_time(times[10].replace(":", "."), prayer="isha")

            for prayer, jt in [
                (Prayer.FAJR, fj),
                (Prayer.DHUHR, zj),
                (Prayer.ASR, aj),
                (Prayer.MAGHRIB, mj),
                (Prayer.ISHA, ij),
            ]:
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {times[1:11]}",
                            target_label="timetable",
                        )
                    )
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
                            raw_text=" ".join(times[:11]),
                            selector=f"dom {dom}",
                        ),
                    )
                )
            i = k
            continue

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=rows, warnings=warnings)
