from __future__ import annotations

import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_day_of_month, parse_month_name
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
    key = "azhar_academy_e857294e"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("azharacademybolton.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        # The homepage links a yearly "SALAAT TIMETABLE" PDF under the media
        # attachments path. The PDF contains explicit multi-month tables with
        # separate "Jamaat Times" columns (right-hand set) for Fajar/Dhuhr/Asr/
        # Maghrib/Isha. No reliable static HTML multi-day jamaat table exists.
        # Target the PDF for the current year (constructed; never a literal year)
        # and parse the jamaat columns from the tabular data.
        y = datetime.now().year
        url = f"https://www.azharacademybolton.org/media/attachments/{y}/01/02/azhar-academy-timetable-{y}.pdf"
        self.targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        warnings: list[ExtractorWarning] = []
        try:
            page_tables = pdf_helpers.extract_tables(artifact.body)
        except Exception:
            return ExtractorResult(rows=[], no_schedule_reason="failed to parse PDF tables")

        if not page_tables:
            return ExtractorResult(rows=[], no_schedule_reason="no tables found in PDF")

        # Column indices in the header row that lists Date/Day/Lunar + begin times + Jamaat Times.
        # Jamaat block starts after the 9th column (0-based): Fajar(j), Dhuhr(j), Asr, Maghrib, Isha
        JAM_COLS: dict[Prayer, int] = {
            Prayer.FAJR: 9,
            Prayer.DHUHR: 10,
            Prayer.ASR: 11,
            Prayer.MAGHRIB: 12,
            Prayer.ISHA: 13,
        }

        rows: list[ExtractorRow] = []
        year = datetime.now().year
        # Title rows contain e.g. "SALAAT TIMETABLE\nJanuary-2026 12 RAJAB 1447 AH"
        month_re = re.compile(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)[-\s]*(\d{2,4})",
            re.IGNORECASE,
        )

        for page_idx, tables_on_page in enumerate(page_tables):
            for raw_table in tables_on_page:
                if not raw_table:
                    continue
                cleaned = [
                    [(cell or "").strip() for cell in row]
                    for row in raw_table
                    if any((c or "").strip() for c in row)
                ]
                if len(cleaned) < 3:
                    continue

                # Locate the column header row (contains "Date" and "Fajar"/"Fajr")
                header_idx: int | None = None
                for i, r in enumerate(cleaned):
                    low = [c.lower() for c in r]
                    if "date" in low and any(k in low for k in ("fajar", "fajr")):
                        if sum(1 for c in r if c) >= 5:
                            header_idx = i
                            break
                if header_idx is None or header_idx + 1 >= len(cleaned):
                    continue

                # Determine month/year for this monthly section from title/header rows
                section_month: int | None = None
                section_year = year
                for r in cleaned[: header_idx + 1]:
                    txt = " ".join(r)
                    m = month_re.search(txt)
                    if m:
                        mon_name = m.group(1)
                        yy = int(m.group(2))
                        section_month = parse_month_name(mon_name)
                        if yy < 100:
                            section_year = 2000 + yy
                        else:
                            section_year = yy
                        break
                if section_month is None:
                    section_month = datetime.now().month

                for r_idx, row in enumerate(cleaned[header_idx + 1 :], start=header_idx + 1):
                    if len(row) <= max(JAM_COLS.values()):
                        continue
                    day_str = row[0] if row else ""
                    day = parse_day_of_month(day_str)
                    if day is None:
                        continue
                    try:
                        d = date(section_year, section_month, day)
                    except ValueError:
                        continue

                    for prayer, col in JAM_COLS.items():
                        if col >= len(row):
                            continue
                        raw = row[col].strip()
                        if not raw or raw in {"-", "–", "—", '"', "''", "“", "”"}:
                            continue
                        jamaat = coerce_time(raw, prayer=prayer.value)
                        if jamaat is None:
                            warnings.append(
                                ExtractorWarning(
                                    code="unparseable_time",
                                    message=f"{d} {prayer.value}: {raw!r}",
                                    target_label="timetable",
                                )
                            )
                            continue
                        window = PLAUSIBLE_WINDOWS.get(prayer.value)
                        if window and not (window[0] <= jamaat <= window[1]):
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
                                jamaat_time=jamaat,
                                timezone=ctx.timezone,
                                evidence=ctx.evidence(
                                    target_label="timetable",
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    raw_text=" | ".join(row),
                                    selector=f"pdf page {page_idx} row {r_idx}",
                                ),
                            )
                        )

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows in PDF",
            )
        return ExtractorResult(rows=rows, warnings=warnings)
