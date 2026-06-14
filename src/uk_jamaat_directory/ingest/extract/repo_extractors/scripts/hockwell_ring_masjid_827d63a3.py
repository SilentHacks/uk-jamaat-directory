import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import find_table
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorEvidence,
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
    key = "hockwell_ring_masjid_827d63a3"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("hockwellringmasjid.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://hockwellringmasjid.org.uk/mobile/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        html = artifact.text()
        rows = []

        # Extract date from the page (format: 13/06/2026)
        date_match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", html)
        if not date_match:
            return ExtractorResult(rows=rows, no_schedule_reason="date not found")

        day, month, year = (
            int(date_match.group(1)),
            int(date_match.group(2)),
            int(date_match.group(3)),
        )
        try:
            row_date = datetime(year, month, day).date()
        except ValueError:
            return ExtractorResult(rows=rows, no_schedule_reason="invalid date")

        # Find the prayer timetable
        table = find_table(html, header_keywords=["prayer", "begins", "iqamah"])
        if not table:
            return ExtractorResult(rows=rows, no_schedule_reason="timetable table not found")

        prayer_map = {
            "Fajr": Prayer.FAJR,
            "Zuhr": Prayer.DHUHR,
            "Asr": Prayer.ASR,
            "Maghrib": Prayer.MAGHRIB,
            "Isha": Prayer.ISHA,
        }

        # Extract prayer times from table body rows
        for table_row in table.body():
            if len(table_row) < 3:
                continue

            prayer_name = table_row[0].strip()
            iqamah_text = table_row[2].strip()

            # Skip non-prayer rows
            if prayer_name == "Sunrise":
                continue

            # Handle Jumuah (special: has two times separated by |)
            if prayer_name == "Jumuah":
                jumuah_times = re.findall(r"(\d{1,2}):(\d{2})", iqamah_text)
                for h, m in jumuah_times:
                    jamaat_time = coerce_time(f"{h}:{m}", prayer=Prayer.JUMUAH.value)
                    if jamaat_time:
                        evidence = ExtractorEvidence(
                            target_label="timetable",
                            target_url=self.targets[0].url,
                            artifact_id=artifact.content_hash,
                            extractor_key=self.key,
                            extractor_version=self.version,
                        )
                        rows.append(
                            ExtractorRow(
                                date=row_date,
                                prayer=Prayer.JUMUAH,
                                jamaat_time=jamaat_time,
                                evidence=evidence,
                            )
                        )
                continue

            # Regular prayers
            if prayer_name not in prayer_map:
                continue

            prayer = prayer_map[prayer_name]

            # Extract iqamah time
            time_match = re.search(r"(\d{1,2}):(\d{2})", iqamah_text)
            if time_match:
                h, m = time_match.group(1), time_match.group(2)
                jamaat_time = coerce_time(f"{h}:{m}", prayer=prayer.value)
                if jamaat_time:
                    evidence = ExtractorEvidence(
                        target_label="timetable",
                        target_url=self.targets[0].url,
                        artifact_id=artifact.content_hash,
                        extractor_key=self.key,
                        extractor_version=self.version,
                    )
                    rows.append(
                        ExtractorRow(
                            date=row_date,
                            prayer=prayer,
                            jamaat_time=jamaat_time,
                            evidence=evidence,
                        )
                    )

        if not rows:
            return ExtractorResult(rows=rows, no_schedule_reason="no extractable rows")

        return ExtractorResult(rows=rows)
