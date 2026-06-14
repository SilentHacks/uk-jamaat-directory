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
    key = "masjid_abdul_aziz_bin_baz_c99acf96"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("masjidbinbaz.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        y = now.year
        m = f"{now.month:02d}"
        url = f"https://masjidbinbaz.com/wp-content/uploads/{y}/{m}/Timetable-{y}-{m}.pdf"
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
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        full_text = pdf_helpers.extract_text(artifact.body)
        page_tables = pdf_helpers.extract_tables(artifact.body)
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []
        year = datetime.now().year
        month: int | None = None
        m = re.search(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)",
            full_text,
            re.IGNORECASE,
        )
        if m:
            month = parse_month_name(m.group(1))
        if month is None:
            month = datetime.now().month
        DATE_COL = 7
        DOW_COLS = (0, 1)
        JAM_COLS: dict[Prayer, int] = {
            Prayer.FAJR: 13,
            Prayer.DHUHR: 22,
            Prayer.ASR: 28,
            Prayer.MAGHRIB: 31,
            Prayer.ISHA: 36,
        }
        for page_idx, tables_on_page in enumerate(page_tables):
            for raw_table in tables_on_page:
                cleaned = [[(cell or "").strip() for cell in row] for row in raw_table if row]
                if len(cleaned) < 2:
                    continue
                header = [c.lower() for c in cleaned[0]]
                if "fajr" not in " ".join(header):
                    continue
                data_rows = cleaned[1:]
                for r_idx, row in enumerate(data_rows):
                    if not row or (not row[0] and (DATE_COL >= len(row) or not row[DATE_COL])):
                        continue
                    date_str = row[DATE_COL] if DATE_COL < len(row) else ""
                    day_num = parse_day_of_month(date_str)
                    if day_num is None:
                        continue
                    try:
                        d = date(year, month, day_num)
                    except ValueError:
                        continue
                    dow = ""
                    for ci in DOW_COLS:
                        if ci < len(row):
                            dow = row[ci].strip().lower()
                            if dow:
                                break
                    is_fri = dow.startswith("fri")
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
                        use_prayer = prayer
                        sess = 1
                        sess_label = None
                        if is_fri and prayer == Prayer.DHUHR:
                            use_prayer = Prayer.JUMUAH
                            sess_label = "Jumuah"
                        rows.append(
                            ExtractorRow(
                                date=d,
                                prayer=use_prayer,
                                jamaat_time=jamaat,
                                session_number=sess,
                                session_label=sess_label,
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
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=rows, warnings=warnings)
