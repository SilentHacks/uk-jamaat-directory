from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.pdf import extract_text
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
    key = "masjid_adam_5d5ccd86"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("masjidadam.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidadam.co.uk/wp-content/uploads/2026/06/June-2026_compressed.pdf",
            kind=TargetKind.PDF,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        text = extract_text(artifact.body)

        rows = []
        current_year = datetime.now().year

        lines = [line.strip() for line in text.split('\n') if line.strip()]

        # PDF extracts columns vertically. Find key markers and work from there.
        # Dates: Look for "Date" header and collect following digit lines
        # Jamaat times: in 5 columns at fixed indices

        dates_list = []
        for i in range(len(lines)):
            if lines[i] == 'Date':
                for j in range(i + 1, len(lines)):
                    if lines[j].isdigit():
                        day_num = int(lines[j])
                        if 1 <= day_num <= 30:
                            dates_list.append(day_num)
                        else:
                            break
                    else:
                        break
                break

        if not dates_list:
            return ExtractorResult(rows=[], no_schedule_reason="Unable to find dates in PDF")

        # Jamaat times are in 5 columns at fixed indices:
        # - Fajr jamaat: line 236 (30 items)
        # - Zuhr jamaat: line 266 (30 items)
        # - Asr jamaat: line 296 (30 items)
        # - Maghrib jamaat: line 326 (30 items)
        # - Isha jamaat: line 356 (30 items)

        jamaat_cols = [
            (236, Prayer.FAJR),
            (266, Prayer.DHUHR),
            (296, Prayer.ASR),
            (326, Prayer.MAGHRIB),
            (356, Prayer.ISHA),
        ]

        # Extract each column for the first 30 rows
        jamaat_data = {}
        for col_start, prayer in jamaat_cols:
            col_data = []
            for row_idx in range(30):
                if col_start + row_idx < len(lines):
                    col_data.append(lines[col_start + row_idx])
            jamaat_data[prayer] = col_data

        # Extract unique dates, preserving order
        unique_dates = []
        seen = set()
        for day_num in dates_list:
            if day_num not in seen:
                unique_dates.append(day_num)
                seen.add(day_num)

        # Build rows
        for row_idx, day_num in enumerate(unique_dates):
            if row_idx >= len(jamaat_data[Prayer.FAJR]):
                break

            date_obj = datetime(current_year, 6, day_num).date()

            for prayer in [Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA]:
                if row_idx >= len(jamaat_data[prayer]):
                    continue

                raw_val = jamaat_data[prayer][row_idx]

                # Skip if it's a quote (means inherit from previous Friday)
                if raw_val == '"':
                    continue

                try:
                    jamaat_time = coerce_time(raw_val, prayer=prayer.value)
                    if jamaat_time is None:
                        continue

                    rows.append(
                        ExtractorRow(
                            date=date_obj,
                            prayer=prayer,
                            jamaat_time=jamaat_time,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=raw_val,
                            ),
                        )
                    )
                except (ValueError, IndexError, TypeError):
                    continue

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="Unable to parse PDF table")

        return ExtractorResult(rows=rows)
