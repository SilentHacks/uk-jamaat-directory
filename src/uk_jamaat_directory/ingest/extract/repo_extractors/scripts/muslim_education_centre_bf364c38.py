import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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

DATE_PATTERN = re.compile(r"Iqamah times for (\d{1,2}\s+\w+\s+\d{4})")

CLASS_TIME_PATTERN = re.compile(
    r'class="(salahfajr|salahzuhr|salah_asr|salah_maghrib|salah_isha|'
    r"iqamah_fajr|iqamah_zuhr|iqamah_asr|iqamah_maghrib|iqamah_isha)"
    r'"[^>]*>.*?<span>([^<]+)</span>',
    re.DOTALL,
)

CLASS_TO_PRAYER = {
    "salahfajr": ("fajr", "start"),
    "salahzuhr": ("zuhr", "start"),
    "salah_asr": ("asr", "start"),
    "salah_maghrib": ("maghrib", "start"),
    "salah_isha": ("isha", "start"),
    "iqamah_fajr": ("fajr", "jamaat"),
    "iqamah_zuhr": ("zuhr", "jamaat"),
    "iqamah_asr": ("asr", "jamaat"),
    "iqamah_maghrib": ("maghrib", "jamaat"),
    "iqamah_isha": ("isha", "jamaat"),
}

PRAYER_MAP = {
    "fajr": Prayer.FAJR,
    "zuhr": Prayer.DHUHR,
    "asr": Prayer.ASR,
    "maghrib": Prayer.MAGHRIB,
    "isha": Prayer.ISHA,
}


class Extractor(BaseMosqueWebsiteExtractor):
    key = "muslim_education_centre_bf364c38"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("mecawt.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://mecawt.co.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        warnings: list[ExtractorWarning] = []

        date_match = DATE_PATTERN.search(html)
        if not date_match:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_date",
                        message="date subheading not found on page",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="date not found on page",
            )
        row_date = parse_date_flexible(
            date_match.group(1), default_year=datetime.now().year
        )
        if row_date is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="bad_date",
                        message=f"unparseable date: {date_match.group(1)!r}",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="unparseable date",
            )

        prayer_data: dict[str, dict[str, str]] = {}
        for match in CLASS_TIME_PATTERN.finditer(html):
            cls = match.group(1)
            time_str = match.group(2).strip()
            prayer_key, kind = CLASS_TO_PRAYER[cls]
            if prayer_key not in prayer_data:
                prayer_data[prayer_key] = {}
            prayer_data[prayer_key][kind] = time_str

        rows: list[ExtractorRow] = []
        for prayer_key in ("fajr", "zuhr", "asr", "maghrib", "isha"):
            data = prayer_data.get(prayer_key)
            if not data:
                continue
            jamaat_raw = data.get("jamaat", "")
            if not jamaat_raw:
                continue
            prayer = PRAYER_MAP[prayer_key]
            jamaat = coerce_time(jamaat_raw, prayer=prayer.value)
            if jamaat is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{row_date} {prayer.value}: jamaat={jamaat_raw!r}",
                        target_label="timetable",
                    )
                )
                continue
            window = PLAUSIBLE_WINDOWS.get(prayer.value)
            if window and not (window[0] <= jamaat <= window[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"{row_date} {prayer.value}: {jamaat_raw!r} outside plausible window",
                        target_label="timetable",
                    )
                )
                continue
            start_raw = data.get("start", "")
            start = (
                coerce_time(start_raw, prayer=prayer.value) if start_raw else None
            )
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
                        raw_text=f"{prayer.value}: start={start_raw}, jamaat={jamaat_raw}",
                        selector=f"[class$='{prayer_key}']",
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
