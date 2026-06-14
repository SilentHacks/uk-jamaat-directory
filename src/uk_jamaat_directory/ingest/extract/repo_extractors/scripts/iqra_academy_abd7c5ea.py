import re
from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
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

JUMUAH_TIME_RE = re.compile(r"(\d{1,2}:\d{2})")

PRAYER_KEYWORDS: list[tuple[str, Prayer]] = [
    ("fajr", Prayer.FAJR),
    ("zuhr", Prayer.DHUHR),
    ("asr1", Prayer.ASR),
    ("magrib", Prayer.MAGHRIB),
    ("isha", Prayer.ISHA),
]


class Extractor(BaseMosqueWebsiteExtractor):
    key = "iqra_academy_abd7c5ea"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("iqraacademy.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://iqraacademy.org/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        tables = extract_tables(artifact.text())
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no tables found on page",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        target_table = None
        for table in tables:
            if any("fajr" in cell.lower() for cell in table.header):
                target_table = table
                break

        if target_table is None or len(target_table.rows) < 3:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_prayer_table",
                        message="no table with FAJR header found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="prayer table not found",
            )

        rows = target_table.rows
        header_lower = [c.lower() for c in rows[0]]

        jamaat_row = None
        begins_row = None
        for r in rows[1:]:
            if not r or not r[0]:
                continue
            label = r[0].strip().lower()
            if "jama" in label:
                jamaat_row = r
            elif "begin" in label:
                begins_row = r

        if jamaat_row is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_jamaat_row",
                        message="Jama'at row not found in table",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="jamaat row not found",
            )

        prayer_columns: dict[Prayer, int] = {}
        for keyword, prayer in PRAYER_KEYWORDS:
            for i, cell in enumerate(header_lower):
                if keyword in cell:
                    prayer_columns[prayer] = i
                    break

        if not prayer_columns:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_prayer_columns",
                        message="no prayer columns matched in header",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no prayer columns found",
            )

        today = date.today()
        warnings: list[ExtractorWarning] = []
        parsed_rows: list[ExtractorRow] = []

        for prayer, idx in prayer_columns.items():
            raw = jamaat_row[idx].strip() if idx < len(jamaat_row) else ""
            if not raw:
                continue
            jamaat = coerce_time(raw, prayer=prayer.value)
            if jamaat is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{today} {prayer.value}: {raw!r}",
                        target_label="timetable",
                    )
                )
                continue

            window = PLAUSIBLE_WINDOWS.get(prayer.value)
            if window and not (window[0] <= jamaat <= window[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"{today} {prayer.value}: {raw!r} outside plausible window",
                        target_label="timetable",
                    )
                )
                continue

            start = None
            if begins_row and idx < len(begins_row):
                start_raw = begins_row[idx].strip()
                if start_raw:
                    start = coerce_time(start_raw, prayer=prayer.value)

            parsed_rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    start_time=start,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join(jamaat_row),
                        selector="Jama'at row in prayer table",
                    ),
                )
            )

        if len(rows) >= 4:
            jumuah_row = rows[3]
            for cell in jumuah_row:
                if "jumuah" in cell.lower():
                    matches = JUMUAH_TIME_RE.findall(cell)
                    for session_num, t in enumerate(matches, start=1):
                        jamaat = coerce_time(t, prayer=Prayer.JUMUAH.value)
                        if jamaat is None:
                            continue
                        jum_window = PLAUSIBLE_WINDOWS.get(Prayer.JUMUAH.value)
                        if jum_window and not (jum_window[0] <= jamaat <= jum_window[1]):
                            warnings.append(
                                ExtractorWarning(
                                    code="implausible_time",
                                    message=f"{today} jumuah: {t!r} outside plausible window",
                                    target_label="timetable",
                                )
                            )
                            continue
                        parsed_rows.append(
                            ExtractorRow(
                                date=today,
                                prayer=Prayer.JUMUAH,
                                jamaat_time=jamaat,
                                session_number=session_num,
                                session_label=f"session {session_num}",
                                timezone=ctx.timezone,
                                evidence=ctx.evidence(
                                    target_label="timetable",
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    raw_text=cell,
                                    selector="Jumuah cell in prayer table",
                                ),
                            )
                        )
                    break

        if not parsed_rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=parsed_rows, warnings=warnings)
