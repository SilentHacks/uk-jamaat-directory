import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_day_of_month, parse_month_name
from uk_jamaat_directory.ingest.extract.helpers.rows import carry_forward
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
    key = "masjid_al_ummah_7f351bc0"
    version = "2026.06.12.1"
    source_match = SourceMatch(
        domains=("abrahamicfoundation.org.uk", "legacy.abrahamicfoundation.org.uk")
    )
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://legacy.abrahamicfoundation.org.uk/wp-content/uploads/2020/08/05-May-Salah-Timetable-Masjid-al-Ummah-1.pdf",
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

        # Parse month/year label from PDF header text e.g. "May-26"
        year = datetime.now().year
        month: int | None = None
        m = re.search(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)[-\s]*(\d{2})",
            full_text,
            re.IGNORECASE,
        )
        if m:
            mon_name = m.group(1)
            yy = int(m.group(2))
            month = parse_month_name(mon_name)
            if yy < 100:
                year = 2000 + yy
        if month is None:
            month = datetime.now().month

        JAM_COLS: dict[Prayer, int] = {
            Prayer.FAJR: 3,
            Prayer.DHUHR: 6,
            Prayer.ASR: 8,
            Prayer.MAGHRIB: 9,
            Prayer.ISHA: 11,
        }

        for page_idx, tables_on_page in enumerate(page_tables):
            for raw_table in tables_on_page:
                cleaned = [[(cell or "").strip() for cell in row] for row in raw_table if row]
                if len(cleaned) < 2:
                    continue
                header = [c.lower() for c in cleaned[0]]
                if "fajr" not in " ".join(header) or "iqamah" not in " ".join(header):
                    continue

                data_rows = cleaned[1:]

                # Carry forward repeated jamaat values shown as blanks/quotes
                for col in JAM_COLS.values():
                    vals = carry_forward(row[col] if col < len(row) else "" for row in data_rows)
                    for i, v in enumerate(vals):
                        if col < len(data_rows[i]):
                            data_rows[i][col] = v

                for r_idx, row in enumerate(data_rows):
                    if not row or not row[0]:
                        continue
                    date_str = row[0]
                    day_num = parse_day_of_month(date_str)
                    if day_num is None:
                        continue
                    try:
                        d = date(year, month, day_num)
                    except ValueError:
                        continue

                    for prayer, col in JAM_COLS.items():
                        if col >= len(row):
                            continue
                        raw = row[col].strip()
                        if not raw or raw in {'"', "''", "“", "”", "-"}:
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
