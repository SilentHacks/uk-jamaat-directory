import json
import re
from datetime import datetime, time as datetime_time

from uk_jamaat_directory.domain import Prayer
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
    key = "norwich_and_norfolk_community_centre_2a8ca4e7"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("norwichmuslims.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/nnma",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()

        # Extract JSON from window.REDUX_STATE embedded in the HTML
        m = re.search(r"window\.REDUX_STATE\s*=\s*['\"](.+?)['\"];", html)
        if not m:
            return ExtractorResult(
                rows=[], no_schedule_reason="redux state not found in HTML"
            )
        
        try:
            encoded_str = m.group(1)
            # Manual percent-decode: replace %XX with corresponding character
            json_str = re.sub(
                r'%([0-9A-Fa-f]{2})',
                lambda m: chr(int(m.group(1), 16)),
                encoded_str
            )
            state_dict = json.loads(json_str)
        except (json.JSONDecodeError, ValueError, KeyError, UnicodeDecodeError):
            return ExtractorResult(
                rows=[], no_schedule_reason="failed to parse embedded JSON"
            )

        # Navigate to timetable in the state
        try:
            timetable = state_dict["masjidbox"]["masjidboxAthany"]["timetable"]
        except KeyError:
            return ExtractorResult(
                rows=[], no_schedule_reason="timetable not found in state"
            )

        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        # Extract prayer times for today's date
        today = datetime.now().date()
        today_str = today.isoformat()

        for entry in timetable:
            entry_date_str = entry.get("date", "")
            if not entry_date_str.startswith(today_str):
                continue

            # Extract iqamah (jamaat) times from the entry
            iqamah_times = entry.get("iqamah", {})
            if not iqamah_times:
                continue

            for prayer_name, prayer_obj in (
                ("fajr", Prayer.FAJR),
                ("dhuhr", Prayer.DHUHR),
                ("asr", Prayer.ASR),
                ("maghrib", Prayer.MAGHRIB),
                ("isha", Prayer.ISHA),
            ):
                iqamah_iso = iqamah_times.get(prayer_name)
                if not iqamah_iso:
                    continue

                # Parse ISO 8601 datetime and extract time
                try:
                    dt = datetime.fromisoformat(iqamah_iso.replace("Z", "+00:00"))
                    jt = dt.time()
                except (ValueError, AttributeError):
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_datetime",
                            message=f"{today} {prayer_name}: {iqamah_iso!r}",
                            target_label="timetable",
                        )
                    )
                    continue

                # Check plausibility
                window = PLAUSIBLE_WINDOWS.get(prayer_name)
                if window and not (window[0] <= jt <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{today} {prayer_name}: {jt} outside plausible window",
                            target_label="timetable",
                        )
                    )
                    continue

                rows.append(
                    ExtractorRow(
                        date=today,
                        prayer=prayer_obj,
                        jamaat_time=jt,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=iqamah_iso,
                            selector=f"iqamah.{prayer_name}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable jamaat rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
