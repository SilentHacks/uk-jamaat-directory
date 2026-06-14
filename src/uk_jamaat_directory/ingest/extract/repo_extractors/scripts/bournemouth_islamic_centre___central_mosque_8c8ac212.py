from __future__ import annotations

import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import (
    parse_day_month,
    parse_day_of_month,
    parse_month_name,
)
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
    key = "bournemouth_islamic_centre___central_mosque_8c8ac212"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("biccm.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.biccm.org.uk/_files/ugd/ea0987_789a9e5652ba41f6aa99235f99003ed4.pdf",
            kind=TargetKind.PDF,
            requires_pdf=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        full_text = pdf_helpers.extract_text(artifact.body)
        page_tables = pdf_helpers.extract_tables(artifact.body)

        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        # Open once to get per-page text for year/month labels (avoids hardcoding)
        page_texts: list[str] = []
        try:
            doc = pdf_helpers.open_pdf(artifact.body)
            for pg in doc:
                page_texts.append(pg.get_text() or "")
            doc.close()
        except Exception:
            page_texts = [""] * max(1, len(page_tables))

        for pi, tables_on_page in enumerate(page_tables):
            page_txt = page_texts[pi] if pi < len(page_texts) else ""
            # year/month from this page's text (falls back to overall)
            pyear = datetime.now().year
            m = re.search(r"\b(20\d{2})\b", page_txt + " " + full_text)
            if m:
                pyear = int(m.group(1))
            pmon = datetime.now().month
            m2 = re.search(
                r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\b",
                page_txt + " " + full_text,
                re.IGNORECASE,
            )
            if m2:
                pm = parse_month_name(m2.group(1))
                if pm:
                    pmon = pm

            for raw_table in tables_on_page:
                cleaned = [[(cell or "").strip() for cell in row] for row in raw_table if row]
                if len(cleaned) < 2:
                    continue
                # detect timetable table by header content
                htext = " ".join(c.lower() for c in cleaned[0] if c)
                if (
                    "fajer" not in htext
                    and "eqama" not in htext
                    and "fajr" not in htext
                    and "date" not in htext
                ):
                    continue

                # locate header row (some tables have a subheader with EQAMA)
                hdr_idx = 0
                for i in range(min(4, len(cleaned))):
                    ht = " ".join((c or "").lower() for c in cleaned[i])
                    if "eqama" in ht or ("fajer" in ht and "date" in ht):
                        hdr_idx = i
                        break
                data_rows = cleaned[hdr_idx + 1 :]

                for r_idx, row in enumerate(data_rows):
                    if not row or not row[0]:
                        continue

                    # collect leading non-time cells as date parts (handles "Wed 18 Feb" or "Thu 1")
                    date_parts: list[str] = []
                    for cell in row:
                        if re.match(r"^\d{1,2}:\d{2}$", cell):
                            break
                        if cell:
                            date_parts.append(cell)
                    date_str = " ".join(date_parts[:3])
                    d = parse_day_month(date_str, year=pyear)
                    if d is None:
                        day = parse_day_of_month(date_str)
                        if day is not None:
                            try:
                                d = date(pyear, pmon, day)
                            except ValueError:
                                d = None
                    if d is None:
                        continue

                    # times in row; jamaat (EQAMA) are typically 2nd,4th,5th,6th,7th in the time sequence
                    time_cells = [c for c in row if re.match(r"^\d{1,2}:\d{2}$", c)]
                    if len(time_cells) < 5:
                        continue

                    jamaat_map: dict[Prayer, str] = {}
                    if len(time_cells) > 1:
                        jamaat_map[Prayer.FAJR] = time_cells[1]
                    if len(time_cells) > 3:
                        jamaat_map[Prayer.DHUHR] = time_cells[3]
                    if len(time_cells) > 4:
                        jamaat_map[Prayer.ASR] = time_cells[4]
                    if len(time_cells) > 5:
                        jamaat_map[Prayer.MAGHRIB] = time_cells[5]
                    if len(time_cells) > 6:
                        jamaat_map[Prayer.ISHA] = time_cells[6]

                    for prayer, raw in jamaat_map.items():
                        if not raw:
                            continue
                        jt = coerce_time(raw, prayer=prayer.value)
                        if jt is None:
                            warnings.append(
                                ExtractorWarning(
                                    code="unparseable_time",
                                    message=f"{d} {prayer.value}: {raw!r}",
                                    target_label="timetable",
                                )
                            )
                            continue
                        window = PLAUSIBLE_WINDOWS.get(prayer.value)
                        if window and not (window[0] <= jt <= window[1]):
                            warnings.append(
                                ExtractorWarning(
                                    code="implausible_time",
                                    message=f"{d} {prayer.value}: {raw!r} outside plausible window",
                                    target_label="timetable",
                                )
                            )
                            continue
                        rows.append(
                            ExtractorRow(
                                date=d,
                                prayer=prayer,
                                jamaat_time=jt,
                                timezone=ctx.timezone,
                                evidence=ctx.evidence(
                                    target_label="timetable",
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    raw_text=" | ".join(row),
                                    selector=f"pdf page {pi} row {r_idx}",
                                ),
                            )
                        )

        # Deduplicate: PDF has repeated calendar pages (cover + per-month), same (date,prayer) appears multiple times.
        seen: set[tuple[date, str, int]] = set()
        unique_rows: list[ExtractorRow] = []
        for r in rows:
            key = (r.date, r.prayer.value, r.session_number)
            if key in seen:
                continue
            seen.add(key)
            unique_rows.append(r)

        if not unique_rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows in PDF",
            )
        return ExtractorResult(rows=unique_rows, warnings=warnings)
