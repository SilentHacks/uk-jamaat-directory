import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
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

_MONTHS = {
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11,
    "DECEMBER": 12,
}

# theme=2 athanplus monthly columns: iqamah (jamaat) cells, plus the single
# maghrib column which is the maghrib congregation time.
_IQAMAH_COLS = {
    Prayer.FAJR: 4,
    Prayer.DHUHR: 7,
    Prayer.ASR: 9,
    Prayer.MAGHRIB: 10,
    Prayer.ISHA: 12,
}


class Extractor(BaseMosqueWebsiteExtractor):
    key = "al_falah_community_centre_0bbbeab7"
    version = "2026.06.18.1"
    source_match = SourceMatch(domains=("alfalahmasjidluton.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://timing.athanplus.com/masjid/widgets/monthly?theme=2&masjid_id=JAm7JRKR",
            kind=TargetKind.HTML,
        ),
    )

    def _month_year(self, html: str) -> tuple[int, int]:
        date_param = re.search(r"date=(\d{4})-(\d{2})-\d{2}", html)
        if date_param:
            return int(date_param.group(2)), int(date_param.group(1))
        month = datetime.now().month
        month_word = re.search(
            r"\b(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|"
            r"SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\b",
            html.upper(),
        )
        if month_word:
            month = _MONTHS[month_word.group(1)]
        return month, datetime.now().year

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(rows=[], no_schedule_reason="no table found")

        month, year = self._month_year(html)
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        for table_row in tables[0].body():
            if len(table_row) < 13:
                continue
            day_num = table_row[0].strip()
            if not day_num[:1].isdigit():
                continue
            try:
                row_date = date(year, month, int(re.sub(r"\D", "", day_num)))
            except (ValueError, TypeError):
                continue

            for prayer, col in _IQAMAH_COLS.items():
                raw = table_row[col].strip() if col < len(table_row) else ""
                if not raw or raw.lower() == "sunset":
                    continue
                jamaat = coerce_time(raw, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{prayer.value}: {raw}",
                            selector=f"monthly table col {col}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no data rows extracted"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
