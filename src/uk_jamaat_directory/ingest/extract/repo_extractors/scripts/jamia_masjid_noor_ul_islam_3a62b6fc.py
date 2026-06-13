import json
import re
from datetime import date, datetime, time

from uk_jamaat_directory.domain import Prayer
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
    key = "jamia_masjid_noor_ul_islam_3a62b6fc"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("noorulislam.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/noor-ul-islam-mosque",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        body = ctx.artifact("timetable")
        if not body.body:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="empty_artifact",
                        message="timetable artifact is empty",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="artifact was empty",
            )

        html = body.text()
        warnings: list[ExtractorWarning] = []

        # Extract Redux state which contains iqamah times
        timetable_data: list = []
        jumuah_iqamah_map: dict[date, list[time]] = {}
        iqamah_map: dict[date, dict[str, time]] = {}

        redux_match = re.search(r"window\.REDUX_STATE\s*=\s*'([^']+)'", html)
        if redux_match:
            try:
                encoded_state = redux_match.group(1)
                # Manual percent-decoding (safe without urllib)
                decoded_state = re.sub(
                    r"%([0-9a-fA-F]{2})",
                    lambda m: chr(int(m.group(1), 16)),
                    encoded_state,
                )
                redux_obj = json.loads(decoded_state)
                timetable_data = (
                    redux_obj.get("masjidbox", {})
                    .get("masjidboxAthany", {})
                    .get("timetable", [])
                )
                for entry in timetable_data:
                    entry_date = date.fromisoformat(
                        entry.get("date", "").split("T")[0]
                    )
                    iqamah = entry.get("iqamah", {})

                    # Map iqamah times by prayer
                    if entry_date not in iqamah_map:
                        iqamah_map[entry_date] = {}

                    for prayer_key in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
                        iq_str = iqamah.get(prayer_key)
                        if iq_str:
                            try:
                                iq_time = datetime.fromisoformat(
                                    iq_str.replace("Z", "+00:00")
                                ).time()
                                iqamah_map[entry_date][prayer_key] = iq_time
                            except ValueError:
                                pass

                    # Jumuah times
                    if "jumuah" in iqamah:
                        jumuah_iqamah_times = []
                        jumuah_times_raw = iqamah["jumuah"]
                        if isinstance(jumuah_times_raw, list):
                            for jt in jumuah_times_raw:
                                try:
                                    jt_dt = datetime.fromisoformat(
                                        jt.replace("Z", "+00:00")
                                    )
                                    jumuah_iqamah_times.append(jt_dt.time())
                                except ValueError:
                                    pass
                        if jumuah_iqamah_times:
                            jumuah_iqamah_map[entry_date] = jumuah_iqamah_times
            except Exception as e:
                warnings.append(
                    ExtractorWarning(
                        code="redux_parse_error",
                        message=f"Failed to parse Redux: {str(e)[:50]}",
                        target_label="timetable",
                    )
                )

        # Extract schema.org JSON-LD events for start times
        ld_json_pattern = r'<script type="application/ld\+json">\s*(\[?\{.*?\}?\]?)\s*</script>'
        matches = re.findall(ld_json_pattern, html, re.DOTALL)

        events_by_date: dict[date, dict[str, list[dict]]] = {}
        for match in matches:
            try:
                data = json.loads(match)
                events = data if isinstance(data, list) else [data]
                for event in events:
                    if event.get("@type") != "Event":
                        continue
                    name = event.get("name", "")
                    if "Prayer" not in name:
                        continue

                    start_date_str = event.get("startDate", "")
                    if not start_date_str:
                        continue

                    event_date = datetime.fromisoformat(
                        start_date_str.replace("Z", "+00:00")
                    ).date()
                    event_time = datetime.fromisoformat(
                        start_date_str.replace("Z", "+00:00")
                    ).time()

                    prayer_label = None
                    for p in ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha", "Jumuah"]:
                        if p in name:
                            prayer_label = p
                            break

                    if not prayer_label:
                        continue

                    if event_date not in events_by_date:
                        events_by_date[event_date] = {}
                    if prayer_label not in events_by_date[event_date]:
                        events_by_date[event_date][prayer_label] = []

                    events_by_date[event_date][prayer_label].append(
                        {"time": event_time, "name": name}
                    )

            except (json.JSONDecodeError, ValueError):
                pass

        if not events_by_date:
            return ExtractorResult(
                rows=[],
                warnings=warnings
                + [
                    ExtractorWarning(
                        code="no_events",
                        message="No prayer events found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no events found",
            )

        extracted_rows: list[ExtractorRow] = []
        for event_date in sorted(events_by_date.keys()):
            day_prayers = events_by_date[event_date]

            for prayer_label in day_prayers:
                if not day_prayers[prayer_label]:
                    continue

                start_time = day_prayers[prayer_label][0]["time"]

                prayer_enum_map = {
                    "Fajr": Prayer.FAJR,
                    "Dhuhr": Prayer.DHUHR,
                    "Asr": Prayer.ASR,
                    "Maghrib": Prayer.MAGHRIB,
                    "Isha": Prayer.ISHA,
                    "Jumuah": Prayer.JUMUAH,
                }
                prayer = prayer_enum_map.get(prayer_label)
                if not prayer:
                    continue

                # Extract jamaat/iqamah time
                jamaat_time = start_time
                if prayer == Prayer.JUMUAH and event_date in jumuah_iqamah_map:
                    jumuah_count = len(
                        [
                            r
                            for r in extracted_rows
                            if r.date == event_date and r.prayer == Prayer.JUMUAH
                        ]
                    )
                    if jumuah_count < len(jumuah_iqamah_map[event_date]):
                        jamaat_time = jumuah_iqamah_map[event_date][jumuah_count]
                elif event_date in iqamah_map:
                    prayer_key_map = {
                        Prayer.FAJR: "fajr",
                        Prayer.DHUHR: "dhuhr",
                        Prayer.ASR: "asr",
                        Prayer.MAGHRIB: "maghrib",
                        Prayer.ISHA: "isha",
                    }
                    prayer_key = prayer_key_map.get(prayer)
                    if prayer_key and prayer_key in iqamah_map[event_date]:
                        jamaat_time = iqamah_map[event_date][prayer_key]

                session_number = 1
                session_label = None
                if prayer == Prayer.JUMUAH:
                    jumuah_count = len(
                        [
                            r
                            for r in extracted_rows
                            if r.date == event_date and r.prayer == Prayer.JUMUAH
                        ]
                    )
                    session_number = jumuah_count + 1
                    session_label = f"session {session_number}"

                evidence = ctx.evidence(
                    target_label="timetable",
                    extractor_key=self.key,
                    extractor_version=self.version,
                    raw_text=day_prayers[prayer_label][0]["name"],
                    selector=f"JSON-LD for {prayer_label} on {event_date}",
                )

                extracted_rows.append(
                    ExtractorRow(
                        date=event_date,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        start_time=start_time,
                        session_number=session_number,
                        session_label=session_label,
                        timezone=ctx.timezone,
                        evidence=evidence,
                    )
                )

        if not extracted_rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings
                + [
                    ExtractorWarning(
                        code="no_extractable_rows",
                        message="No extractable rows",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no extractable rows",
            )

        return ExtractorResult(rows=extracted_rows, warnings=warnings)
