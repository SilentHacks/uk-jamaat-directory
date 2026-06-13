import re
from datetime import date

from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
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
    key = "masjid_bilal____sunni__531d2e31"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("masjidbilal.uk", "www.masjidbilal.uk"))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.masjidbilal.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(rows=[], no_schedule_reason="no table found")

        extracted_rows: list[ExtractorRow] = []

        for table in tables:
            if not table.header or len(table.body()) == 0:
                continue

            # Try to find date in header or first row
            row_date: date | None = None
            header_text = " ".join(table.header)
            
            # Look for date pattern in header
            date_match = re.search(r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})', header_text)
            if date_match:
                date_str = f"{date_match.group(1)} {date_match.group(2)} {date_match.group(3)}"
                row_date = parse_date_flexible(date_str, default_year=2026)

            if not row_date:
                continue

            for row_idx, row in enumerate(table.body()):
                if len(row) < 3:
                    continue

                prayer_name = row[0].strip().lower()
                if prayer_name in ("sunrise", "begins", "prayer"):
                    continue

                prayer = parse_prayer_label(prayer_name)
                if not prayer:
                    continue

                begins_text = row[1].strip() if len(row) > 1 else ""
                iqamah_text = row[2].strip() if len(row) > 2 else ""

                if not begins_text or begins_text.lower() in ("begins", "adhan"):
                    begins_text = ""
                if not iqamah_text or iqamah_text.lower() in ("jamaat", "iqamah"):
                    continue

                # Handle Jumuah with multiple sessions
                if prayer.value == "jumuah":
                    times = re.findall(r'(\d{1,2}:\d{2})', iqamah_text)
                    for sidx, t in enumerate(times, 1):
                        jt = coerce_time(t, prayer="jumuah")
                        if jt is None:
                            continue
                        extracted_rows.append(
                            ExtractorRow(
                                date=row_date,
                                prayer=prayer,
                                jamaat_time=jt,
                                start_time=None,
                                session_number=sidx,
                                timezone=ctx.timezone,
                                evidence=ctx.evidence(
                                    target_label="timetable",
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    raw_text=t,
                                    selector=f"table tbody tr:nth-child({row_idx + 2})",
                                ),
                            )
                        )
                else:
                    jamaat = coerce_time(iqamah_text, prayer=prayer.value)
                    if jamaat is None:
                        continue

                    start = coerce_time(begins_text, prayer=prayer.value) if begins_text else None

                    extracted_rows.append(
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
                                raw_text=" | ".join(row[:3]),
                                selector=f"table tbody tr:nth-child({row_idx + 2})",
                            ),
                        )
                    )

        if not extracted_rows:
            return ExtractorResult(rows=[], no_schedule_reason="no extractable rows")

        # Sort by date, prayer order, session
        order = {
            "fajr": 0,
            "dhuhr": 1,
            "asr": 2,
            "maghrib": 3,
            "isha": 4,
            "jumuah": 5,
        }
        extracted_rows.sort(
            key=lambda r: (r.date, order.get(r.prayer.value, 999), r.session_number or 1)
        )

        return ExtractorResult(rows=extracted_rows)
