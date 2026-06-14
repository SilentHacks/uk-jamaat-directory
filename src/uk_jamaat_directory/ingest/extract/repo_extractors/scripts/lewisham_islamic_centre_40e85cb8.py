import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import dates, times
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    BaseMosqueWebsiteExtractor,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "lewisham_islamic_centre_40e85cb8"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("lewishamislamiccentre.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    target_label = "timetable"
    targets = (
        TargetSpec(
            label="timetable",
            url="https://lewishamislamiccentre.com/prayer-times/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        result_rows = []

        # Find all day-date entries
        day_matches = list(re.finditer(r'day-date">([^<]+?)<', html))

        for day_match in day_matches:
            date_str = day_match.group(1).strip()
            if not date_str or date_str.lower() == "date":
                continue

            try:
                parsed_date = dates.parse_date_flexible(date_str, default_year=datetime.now().year)
                if not parsed_date:
                    continue
            except Exception:
                continue

            # From this point, search forward for prayer blocks in this day's section
            start_pos = day_match.end()
            # Find the next day-date or end of string
            next_day_match = re.search(r'day-date">', html[start_pos:])
            end_pos = start_pos + next_day_match.start() if next_day_match else len(html)

            day_section = html[start_pos:end_pos]

            # Extract each prayer and its jamaat time
            prayer_pattern = re.compile(r'prayer-title">([^<]+?)<.*?jam">([^<]+?)<', re.DOTALL)

            for pmatch in prayer_pattern.finditer(day_section):
                prayer_name = pmatch.group(1).strip().replace("'", "").replace("&rsquo;", "")
                jamaat_str = pmatch.group(2).strip()

                prayer_enum = None
                if prayer_name == "Fajr":
                    prayer_enum = Prayer.FAJR
                elif prayer_name == "Dhuhr":
                    prayer_enum = Prayer.DHUHR
                elif prayer_name == "Asr":
                    prayer_enum = Prayer.ASR
                elif prayer_name == "Maghrib":
                    prayer_enum = Prayer.MAGHRIB
                elif prayer_name == "Isha":
                    prayer_enum = Prayer.ISHA

                if not prayer_enum or not jamaat_str:
                    continue

                jamaat_time = times.coerce_time(jamaat_str)
                if not jamaat_time:
                    continue

                result_rows.append(
                    ExtractorRow(
                        date=parsed_date,
                        prayer=prayer_enum,
                        jamaat_time=jamaat_time,
                        evidence=ctx.evidence(
                            target_label=self.target_label,
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{prayer_name} {jamaat_str}",
                            selector=f"{date_str} {prayer_name}",
                        ),
                    )
                )

        if not result_rows:
            return ExtractorResult(rows=[], no_schedule_reason="no extractable rows")

        return ExtractorResult(rows=result_rows)
