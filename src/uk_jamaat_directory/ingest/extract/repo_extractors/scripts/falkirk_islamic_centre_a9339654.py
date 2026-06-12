import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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

PRAYER_MAP = {
    "fajr": Prayer.FAJR,
    "zuhr": Prayer.DHUHR,
    "asr": Prayer.ASR,
    "maghrib": Prayer.MAGHRIB,
    "isha": Prayer.ISHA,
}


class Extractor(BaseMosqueWebsiteExtractor):
    key = "falkirk_islamic_centre_a9339654"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("falkirkcentralmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://falkirkcentralmosque.com/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        timetable_table = None
        for table in tables:
            if len(table.rows) < 2:
                continue
            header_row = " ".join(table.rows[1]).lower()
            if "prayer" in header_row and "adhan" in header_row and "iqamah" in header_row:
                timetable_table = table
                break

        if timetable_table is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="prayer timetable table not found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        row_date = date.today()
        if timetable_table.rows:
            parsed = parse_date_flexible(timetable_table.rows[0][0], default_year=datetime.now().year)
            if parsed is not None:
                row_date = parsed

        for row_data in timetable_table.rows[2:]:
            if len(row_data) < 2:
                continue
            prayer_name = row_data[0].strip().lower()
            if prayer_name == "sunrise":
                continue
            if prayer_name not in PRAYER_MAP:
                continue

            prayer = PRAYER_MAP[prayer_name]
            jamaat_raw = row_data[2].strip() if len(row_data) > 2 else ""
            if not jamaat_raw:
                continue

            jamaat = coerce_time(jamaat_raw, prayer=prayer.value)
            if jamaat is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{row_date} {prayer.value}: {jamaat_raw!r}",
                        target_label="timetable",
                    )
                )
                continue

            start_raw = row_data[1].strip() if len(row_data) > 1 else ""
            start = coerce_time(start_raw, prayer=prayer.value) if start_raw else None

            rows.append(
                ExtractorRow(
                    date=row_date,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    start_time=start,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join(row_data),
                        selector="prayer timetable table",
                    ),
                )
            )

        text = html_helpers.html_to_text(html)
        jumuah_times = re.findall(
            r"Jumu[^\w]?ah.*?(\d{1,2}:\d{2}).*?(\d{1,2}:\d{2})",
            text,
            re.IGNORECASE,
        )
        if jumuah_times:
            times = jumuah_times[0]
            for session_num, raw_time in [(1, times[0]), (2, times[1])]:
                jt = coerce_time(raw_time, prayer=Prayer.JUMUAH.value)
                if jt:
                    rows.append(
                        ExtractorRow(
                            date=row_date,
                            prayer=Prayer.JUMUAH,
                            jamaat_time=jt,
                            session_number=session_num,
                            session_label=f"{session_num}st Iqamah" if session_num == 1 else f"{session_num}nd Iqamah",
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"Jumu'ah {raw_time}",
                                selector="Jumu'ah text",
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
