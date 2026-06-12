import json
import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_day_of_month
from uk_jamaat_directory.ingest.extract.helpers.relative import add_minutes
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
    key = "newark_islamic_centre_9d59598d"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("newarkislamiccentre.co.uk", "mawaqit.net"))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://mawaqit.net/en/w/masjid-e-bilaal-nottingham-ng7-2et-united-kingdom?showOnly5PrayerTimes=0",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()

        match = re.search(r"var confData\s*=\s*(\{.+?\});", html, re.DOTALL)
        if not match:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="confData JSON not found",
                warnings=[
                    ExtractorWarning(
                        code="no_json",
                        message="confData JSON not found in mawaqit widget page",
                        target_label="timetable",
                    )
                ],
            )

        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="confData JSON parse error",
                warnings=[
                    ExtractorWarning(
                        code="json_parse_error",
                        message="failed to parse confData JSON",
                        target_label="timetable",
                    )
                ],
            )

        iqama_calendar = data.get("iqamaCalendar")
        if not iqama_calendar:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="iqamaCalendar not found in confData",
                warnings=[
                    ExtractorWarning(
                        code="no_iqama_calendar",
                        message="iqamaCalendar not found in confData",
                        target_label="timetable",
                    )
                ],
            )

        prayer_calendar = data.get("calendar")
        jumua = data.get("jumua", "")
        jumua2 = data.get("jumua2", "")

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        year = datetime.now().year

        for month_index, month_data in enumerate(iqama_calendar, start=1):
            if not isinstance(month_data, dict):
                continue
            for day_str, times in month_data.items():
                day = parse_day_of_month(day_str)
                if day is None:
                    continue
                try:
                    row_date = date(year, month_index, day)
                except ValueError:
                    continue

                if not isinstance(times, list) or len(times) < 5:
                    continue

                maghrib_adhan = None
                if prayer_calendar and month_index - 1 < len(prayer_calendar):
                    prayer_month = prayer_calendar[month_index - 1]
                    if isinstance(prayer_month, dict) and day_str in prayer_month:
                        prayer_day = prayer_month[day_str]
                        if isinstance(prayer_day, list) and len(prayer_day) >= 5:
                            maghrib_adhan = coerce_time(prayer_day[4], prayer="maghrib")

                prayer_map = [
                    (Prayer.FAJR, times[0]),
                    (Prayer.DHUHR, times[1]),
                    (Prayer.ASR, times[2]),
                    (Prayer.MAGHRIB, times[3]),
                    (Prayer.ISHA, times[4]),
                ]

                for prayer, raw in prayer_map:
                    if not raw:
                        continue

                    raw_str = str(raw).strip()

                    if raw_str.startswith("+"):
                        offset_str = raw_str[1:]
                        try:
                            offset = int(offset_str)
                        except ValueError:
                            continue
                        if prayer == Prayer.MAGHRIB and maghrib_adhan:
                            jamaat = add_minutes(maghrib_adhan, offset)
                        else:
                            continue
                    else:
                        jamaat = coerce_time(raw_str, prayer=prayer.value)
                        if jamaat is None:
                            warnings.append(
                                ExtractorWarning(
                                    code="unparseable_time",
                                    message=f"{row_date} {prayer.value}: {raw_str!r}",
                                    target_label="timetable",
                                )
                            )
                            continue

                    window = PLAUSIBLE_WINDOWS.get(prayer.value)
                    if window and not (window[0] <= jamaat <= window[1]):
                        warnings.append(
                            ExtractorWarning(
                                code="implausible_time",
                                message=f"{row_date} {prayer.value}: {raw_str!r} outside plausible window",
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
                                raw_text=f"{row_date} {prayer.value}: {raw_str}",
                                selector=f"iqamaCalendar month={month_index} day={day}",
                            ),
                        )
                    )

        if jumua:
            jumuah_time = coerce_time(jumua, prayer="jumuah")
            if jumuah_time:
                for month_index in range(1, 13):
                    for day_num in range(1, 32):
                        try:
                            d = date(year, month_index, day_num)
                        except ValueError:
                            continue
                        if d.weekday() == 4:
                            rows.append(
                                ExtractorRow(
                                    date=d,
                                    prayer=Prayer.JUMUAH,
                                    jamaat_time=jumuah_time,
                                    session_number=1,
                                    timezone=ctx.timezone,
                                    evidence=ctx.evidence(
                                        target_label="timetable",
                                        extractor_key=self.key,
                                        extractor_version=self.version,
                                        raw_text=f"Jumuah: {jumua}",
                                        selector="confData.jumua",
                                    ),
                                )
                            )

        if jumua2:
            jumuah2_time = coerce_time(jumua2, prayer="jumuah")
            if jumuah2_time:
                for month_index in range(1, 13):
                    for day_num in range(1, 32):
                        try:
                            d = date(year, month_index, day_num)
                        except ValueError:
                            continue
                        if d.weekday() == 4:
                            rows.append(
                                ExtractorRow(
                                    date=d,
                                    prayer=Prayer.JUMUAH,
                                    jamaat_time=jumuah2_time,
                                    session_number=2,
                                    timezone=ctx.timezone,
                                    evidence=ctx.evidence(
                                        target_label="timetable",
                                        extractor_key=self.key,
                                        extractor_version=self.version,
                                        raw_text=f"Jumuah 2: {jumua2}",
                                        selector="confData.jumua2",
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
