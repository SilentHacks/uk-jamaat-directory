from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_month_name
from uk_jamaat_directory.ingest.extract.helpers.rows import carry_forward
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
    key = "mosque_al_noor_7d05a03c"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("masjidalnoor.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # The mosque publishes a monthly PDF timetable. The homepage links directly
        # to the current month's PDF asset (no HTML table or jamaat feed is present).
        # This is a Wix-hosted opaque asset path; when the mosque replaces the PDF
        # for a new month the link on the homepage will change — bump version and
        # update the URL here at that time. We target the PDF as published today.
        # Jumuah times are also stated in text on the homepage (not part of this extract).
        self._targets = (
            TargetSpec(
                label="timetable",
                url="https://www.masjidalnoor.co.uk/_files/ugd/31764d_9e53f3156ff543299247bb67d9401b43.pdf",
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        try:
            doc = pdf_helpers.open_pdf(artifact.body)
            page = doc[0]
            words = page.get_text("words")
            full_text = page.get_text() or ""
            doc.close()
        except Exception as exc:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="pdf_open_error",
                        message=f"failed to open/parse PDF: {exc}",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="failed to open PDF",
            )

        # Determine year/month from PDF header text (e.g. "June") if present.
        year = datetime.now().year
        month = datetime.now().month
        for m in re.finditer(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)",
            full_text,
            re.IGNORECASE,
        ):
            mon = parse_month_name(m.group(1))
            if mon:
                month = mon
                break

        # Use table extraction to preserve column alignment for blank/carry cells.
        page_tables = pdf_helpers.extract_tables(artifact.body)
        day_to_jamaat: dict[int, list[str]] = {}
        if page_tables and page_tables[0]:
            raw_table = page_tables[0][0] if page_tables[0] else []
            cleaned = [[(cell or "").strip() for cell in row] for row in raw_table if row]
            # First ~3 rows are headers; data starts at row 3.
            data_rows = cleaned[3:] if len(cleaned) > 3 else cleaned
            for r in data_rows:
                day: int | None = None
                for c in range(min(8, len(r))):
                    v = r[c]
                    if v.isdigit():
                        dn = int(v)
                        if 1 <= dn <= 31:
                            day = dn
                            break
                if day is None:
                    continue

                def getc(i: int) -> str:
                    return r[i] if i < len(r) else ""

                fj = getc(10)
                zj = getc(19)
                aj = getc(25)
                mj = getc(28)
                ij = getc(34)
                day_to_jamaat[day] = [fj, zj, aj, mj, ij]

        if day_to_jamaat:
            days_sorted = sorted(day_to_jamaat.keys())
            cols: list[list[str]] = [[] for _ in range(5)]
            for d in days_sorted:
                raw5 = day_to_jamaat.get(d, [""] * 5)
                for c in range(5):
                    val = raw5[c] if c < len(raw5) else ""
                    cols[c].append(val)
            carried = [carry_forward(list(c)) for c in cols]

            PRAYERS_5 = [Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA]
            for idx, d in enumerate(days_sorted):
                try:
                    rd = date(year, month, d)
                except ValueError:
                    continue
                is_fri = rd.weekday() == 4
                for pi, prayer in enumerate(PRAYERS_5):
                    raw = carried[pi][idx] if pi < len(carried) else ""
                    if not raw:
                        continue
                    use_prayer = Prayer.JUMUAH if (is_fri and prayer == Prayer.DHUHR) else prayer
                    sess = 1
                    sess_label: str | None = "1st Jumuah" if use_prayer == Prayer.JUMUAH else None
                    jt = coerce_time(raw, prayer=use_prayer.value)
                    if jt is None:
                        warnings.append(
                            ExtractorWarning(
                                code="unparseable_time",
                                message=f"{rd} {use_prayer.value}: {raw!r}",
                                target_label="timetable",
                            )
                        )
                        continue
                    rows.append(
                        ExtractorRow(
                            date=rd,
                            prayer=use_prayer,
                            jamaat_time=jt,
                            session_number=sess,
                            session_label=sess_label,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=raw,
                                selector=f"day {d}",
                            ),
                        )
                    )

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=rows, warnings=warnings)
