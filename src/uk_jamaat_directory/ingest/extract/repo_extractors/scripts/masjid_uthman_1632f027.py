from __future__ import annotations

import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_day_of_month, parse_month_name
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
    key = "masjid_uthman_1632f027"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("snicc.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        y = now.year
        m = now.month
        month_name = now.strftime("%B")
        if m == 1:
            uy, um = y - 1, 12
        else:
            uy, um = y, m - 1
        url = f"https://snicc.org.uk/wp-content/uploads/{uy}/{um:02d}/{month_name}-{y}-new.pdf"
        self.targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )

    def _year_month_from_ctx(self, ctx: ExtractContext) -> tuple[int, int]:
        url = ""
        try:
            url = ctx.artifact("timetable").target_url or ""
        except Exception:
            pass
        if not url:
            for t in self.targets:
                if t.label == "timetable":
                    url = t.url
                    break
        year = datetime.now().year
        month = datetime.now().month
        m = re.search(r"(20\d{2})", url)
        if m:
            year = int(m.group(1))
        m2 = re.search(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)",
            url,
            re.IGNORECASE,
        )
        if m2:
            mon = parse_month_name(m2.group(1))
            if mon is not None:
                month = mon
        return year, month

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        warnings: list[ExtractorWarning] = []
        year, month = self._year_month_from_ctx(ctx)
        tables_pages = pdf_helpers.extract_tables(artifact.body)
        rows_out: list[ExtractorRow] = []
        for page_tables in tables_pages:
            for raw in page_tables:
                if not raw or len(raw) < 3:
                    continue
                cleaned = [[(c or "") for c in row] for row in raw]
                header_text = " ".join(" ".join(r).lower() for r in cleaned[:3])
                if "fajr" not in header_text and "jamat" not in header_text:
                    continue
                for r in cleaned[2:]:
                    if not any(x.strip() for x in r):
                        continue

                    def parts(s: str) -> list[str]:
                        return [p.strip() for p in (s or "").split("\n") if p.strip()]

                    day_parts = parts(r[0]) if len(r) > 0 else []
                    date_parts = parts(r[1]) if len(r) > 1 else []
                    n = max(len(day_parts), len(date_parts), 1)
                    if not date_parts:
                        n = 1
                        day_parts = [r[0].strip()] if r else []
                        date_parts = [r[1].strip()] if len(r) > 1 else []
                    col_map = {
                        Prayer.FAJR: 3,
                        Prayer.DHUHR: 6,
                        Prayer.ASR: 8,
                        Prayer.MAGHRIB: 9,
                        Prayer.ISHA: 11,
                    }
                    for i in range(n):
                        dstr = (
                            date_parts[i]
                            if i < len(date_parts)
                            else (date_parts[-1] if date_parts else "")
                        )
                        daystr = (
                            day_parts[i]
                            if i < len(day_parts)
                            else (day_parts[-1] if day_parts else "")
                        )
                        day_num = parse_day_of_month(dstr)
                        if day_num is None:
                            continue
                        try:
                            row_date = date(year, month, day_num)
                        except ValueError:
                            continue
                        is_fri = daystr.lower().startswith("fri")
                        for prayer, col in col_map.items():
                            rawt = ""
                            if col < len(r):
                                sp = [p.strip() for p in r[col].split("\n") if p.strip()]
                                if sp:
                                    rawt = sp[i] if i < len(sp) else sp[-1]
                            if not rawt:
                                continue
                            jt = coerce_time(rawt, prayer=prayer.value)
                            if jt is None:
                                warnings.append(
                                    ExtractorWarning(
                                        code="unparseable_time",
                                        message=f"{row_date} {prayer.value}: {rawt!r}",
                                        target_label="timetable",
                                    )
                                )
                                continue
                            use_prayer = (
                                Prayer.JUMUAH if (prayer is Prayer.DHUHR and is_fri) else prayer
                            )
                            rows_out.append(
                                ExtractorRow(
                                    date=row_date,
                                    prayer=use_prayer,
                                    jamaat_time=jt,
                                    timezone=ctx.timezone,
                                    evidence=ctx.evidence(
                                        target_label="timetable",
                                        extractor_key=self.key,
                                        extractor_version=self.version,
                                        raw_text=" | ".join((c or "") for c in r),
                                        selector=f"row~{i}",
                                    ),
                                )
                            )
        if not rows_out:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows_out, warnings=warnings)
