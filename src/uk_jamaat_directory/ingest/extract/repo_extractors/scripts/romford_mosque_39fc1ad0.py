import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
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

_DATE_TIME_RE = re.compile(
    r"(?P<date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), "
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}, \d{4})"
    r" \d{1,2} \w+ \w+ \d{4}"
    r"(?P<times>(?: \d{1,2}:\d{2}| --){12})"
)

# Time token indices (0-based) within the 12-value array:
# Fajr_athan=0, Fajr_iqamah=1, Shuruq_athan=2, Shuruq_iqamah=3,
# Dhuhr_athan=4, Dhuhr_iqamah=5, Asr_athan=6, Asr_iqamah=7,
# Maghrib_athan=8, Maghrib_iqamah=9, Isha_athan=10, Isha_iqamah=11
_IQAMAH_COLUMNS: dict[Prayer, int] = {
    Prayer.FAJR: 1,
    Prayer.DHUHR: 5,
    Prayer.ASR: 7,
    Prayer.MAGHRIB: 9,
    Prayer.ISHA: 11,
}


class Extractor(BaseMosqueWebsiteExtractor):
    key = "romford_mosque_39fc1ad0"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("romfordmosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        self._targets = (
            TargetSpec(
                label="timetable",
                url="http://romfordmosque.co.uk/",
                kind=TargetKind.RENDERED_HTML,
                requires_javascript=True,
            ),
        )
        super().__init__()

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        text = artifact.text()
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        for match in _DATE_TIME_RE.finditer(text):
            date_str = match.group("date").strip().rstrip(",")
            row_date = parse_date_flexible(date_str, default_year=datetime.now().year)
            if row_date is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_date",
                        message=f"could not parse date: {date_str!r}",
                        target_label="timetable",
                    )
                )
                continue

            times_str = match.group("times").strip()
            time_tokens = times_str.split()

            for prayer, col_idx in _IQAMAH_COLUMNS.items():
                if col_idx >= len(time_tokens):
                    continue
                raw = time_tokens[col_idx]
                if not raw or raw == "--":
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
                            raw_text=match.group(0),
                            selector=f"text row matching {row_date}",
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
