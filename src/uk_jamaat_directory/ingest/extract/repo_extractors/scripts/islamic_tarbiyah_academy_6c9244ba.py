import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
    BaseMosqueWebsiteExtractor,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "islamic_tarbiyah_academy_6c9244ba"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("islamictarbiyah.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    target_label = "timetable"
    targets = (
        TargetSpec(
            label="timetable",
            url="https://islamictarbiyah.com/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        html = artifact.text()

        # Find the date in the page: looks for "June 13, 2026" etc.
        date_match = re.search(r'(\w+)\s+(\d{1,2}),\s+(\d{4})', html)
        if not date_match:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no date found in timetable",
            )

        date_str = date_match.group(0)
        try:
            date_obj = parse_date_flexible(date_str, default_year=datetime.now().year)
            if date_obj is None:
                return ExtractorResult(
                    rows=[],
                    no_schedule_reason="could not parse date",
                )
        except Exception:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="could not parse date",
            )

        rows = []
        prayer_map = {
            'Fajr': Prayer.FAJR,
            'Zuhr': Prayer.DHUHR,
            'Asr': Prayer.ASR,
            'Maghrib': Prayer.MAGHRIB,
            'Isha': Prayer.ISHA,
        }

        # Find rows with prayer times
        for prayer_name, prayer_obj in prayer_map.items():
            pattern = prayer_name + r'.*?</tr>'
            match = re.search(pattern, html, re.DOTALL)
            if not match:
                continue

            row_html = match.group(0)
            cells = re.findall(r'<td[^>]*>([^<]*)</td>', row_html)

            if len(cells) < 2:
                continue

            jamaat_time_str = cells[1].strip()
            if not jamaat_time_str:
                continue

            try:
                jamaat_time = coerce_time(jamaat_time_str, prayer=prayer_name.lower())
                if jamaat_time is None:
                    continue
                row = ExtractorRow(
                    date=date_obj,
                    prayer=prayer_obj,
                    jamaat_time=jamaat_time,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=f"{prayer_name} {jamaat_time_str}",
                    ),
                )
                rows.append(row)
            except Exception:
                pass

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no prayer times extracted",
            )

        return ExtractorResult(rows=rows)
