import json
import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "north_devon_islamic_culture_centre_69898210"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("barnstapleislamiccentre.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://barnstapleislamiccentre.co.uk/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="awaiting OCR")

        html = artifact.text()

        # The site uses an iframe to embed a third-party MosqueScreen app
        # The timetable data is not available as static HTML without JS rendering
        # The external app (vercel.app) is not an approved target domain
        if "north-devon-ic.vercel.app" in html:
            return ExtractorResult(rows=[], no_schedule_reason="awaiting OCR")

        rows = []

        try:
            # Try to extract JSON data if it's embedded in the page
            json_match = re.search(r'"today":(\{[^}]*?"fajr".*?"isha"[^}]*\})', html, re.DOTALL)
            if not json_match:
                return ExtractorResult(rows=[], no_schedule_reason="awaiting OCR")

            json_str = json_match.group(1)
            today_data = json.loads(json_str)

            # Extract date from the HTML
            date_match = re.search(r"day_of_month.*?['\"](\d{1,2})['\"]", html)
            month_match = re.search(r'"month".*?[\'"](\d{1,2})[\'"]', html)

            if not date_match or not month_match:
                return ExtractorResult(rows=[], no_schedule_reason="awaiting OCR")

            day = int(date_match.group(1))
            month = int(month_match.group(1))
            year = datetime.now().year

            # Extract prayer times - only extract jamaat/congregation times
            prayers = {
                Prayer.FAJR: "fajr",
                Prayer.DHUHR: "zuhr",
                Prayer.ASR: "asr",
                Prayer.MAGHRIB: "maghrib",
                Prayer.ISHA: "isha",
            }

            for prayer, key in prayers.items():
                if key in today_data:
                    prayer_data = today_data[key]
                    if isinstance(prayer_data, dict) and "congregation_start" in prayer_data:
                        jamaat_time_str = prayer_data["congregation_start"]
                        jamaat_time = coerce_time(jamaat_time_str)
                        if jamaat_time:
                            rows.append(
                                ExtractorRow(
                                    date=f"{year:04d}-{month:02d}-{day:02d}",
                                    prayer=prayer,
                                    jamaat=jamaat_time,
                                )
                            )

            if not rows:
                return ExtractorResult(rows=[], no_schedule_reason="awaiting OCR")

            return ExtractorResult(rows=rows)

        except (json.JSONDecodeError, KeyError, ValueError):
            return ExtractorResult(rows=[], no_schedule_reason="awaiting OCR")
