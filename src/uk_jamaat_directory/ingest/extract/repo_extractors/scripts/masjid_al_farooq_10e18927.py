import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS, coerce_time
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
    key = "masjid_al_farooq_10e18927"
    version = "2026.06.13.2"
    source_match = SourceMatch(domains=("masjidalfarouq.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self):
        super().__init__()
        now = datetime.now()
        self.targets = (
            TargetSpec(
                label="timetable",
                url=f"https://www.masjidalfarouq.org.uk/timetables/{now.year}/{now.month}",
                kind=TargetKind.HTML,
            ),
        )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        if hasattr(artifact, "text") and callable(artifact.text):
            html = artifact.text()
        elif isinstance(artifact.body, bytes):
            html = artifact.body.decode("utf-8", errors="ignore")
        else:
            html = artifact.body

        rows: list[ExtractorRow] = []
        table_match = re.search(r"<table[^>]*>(.*?)</table>", html, re.DOTALL)
        if not table_match:
            return ExtractorResult(rows=[], no_schedule_reason="no table found")

        table_html = table_match.group(0)
        tr_rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL)

        if not tr_rows:
            return ExtractorResult(rows=[], no_schedule_reason="no table rows found")

        # Skip header row
        for tr_html in tr_rows[1:]:
            cells = re.findall(r"<th[^>]*>(.*?)</th>|<td[^>]*>(.*?)</td>", tr_html, re.DOTALL)
            cells = [(cell[0] or cell[1]).strip() for cell in cells]

            if len(cells) < 14:
                continue

            try:
                day_str = cells[0].strip()
                if not day_str.isdigit():
                    continue

                day = int(day_str)
                now = datetime.now()
                date = datetime(now.year, now.month, day).date()

                # Extract jamaat times (indices 4, 7, 9, 11, 13)
                prayers_data = [
                    (Prayer.FAJR, cells[4], 4),
                    (Prayer.DHUHR, cells[7], 7),
                    (Prayer.ASR, cells[9], 9),
                    (Prayer.MAGHRIB, cells[11], 11),
                    (Prayer.ISHA, cells[13], 13),
                ]

                for prayer, raw_time, _ in prayers_data:
                    jamaat = coerce_time(raw_time, prayer=prayer.value)
                    if jamaat is None:
                        continue

                    # Validate against plausible window
                    window = PLAUSIBLE_WINDOWS.get(prayer.value)
                    if window and not (window[0] <= jamaat <= window[1]):
                        continue

                    rows.append(
                        ExtractorRow(
                            date=date,
                            prayer=prayer,
                            jamaat_time=jamaat,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"{day} {prayer.value} {raw_time}",
                            ),
                        )
                    )
            except (ValueError, IndexError):
                continue

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no extractable rows")

        return ExtractorResult(rows=rows)
