from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS, coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
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
    key = "medina_mosque_126ff42d"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("medinamosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://medinamosque.org.uk/",
            kind=TargetKind.HTML,
        ),
    )
    target_label = "timetable"

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        # Prayer name to Prayer enum mapping
        prayer_map = {
            "fajr": Prayer.FAJR,
            "zuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        for raw_table in tables:
            # Find header row (contains "Prayer" and "Iqamah")
            header_idx = None
            date_str = None
            for i, row in enumerate(raw_table.rows):
                low = [c.lower() for c in row]
                if "prayer" in low and "iqamah" in low:
                    header_idx = i
                    # Date is in the row just before header
                    if i > 0 and len(raw_table.rows[i - 1]) == 1:
                        date_str = raw_table.rows[i - 1][0]
                    break

            if header_idx is None or not date_str:
                continue

            # Parse date
            try:
                row_date = date.fromisoformat(date_str[:10])
            except (ValueError, IndexError):
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_date",
                        message=f"Could not parse date from: {date_str}",
                        target_label=self.target_label,
                    )
                )
                continue

            # Find column indices for Iqamah (jamaat time)
            header = [c.strip() for c in raw_table.rows[header_idx]]
            iqamah_idx = None
            for idx, cell in enumerate(header):
                if "iqamah" in cell.lower():
                    iqamah_idx = idx
                    break

            if iqamah_idx is None:
                warnings.append(
                    ExtractorWarning(
                        code="no_iqamah_column",
                        message="Could not find Iqamah column",
                        target_label=self.target_label,
                    )
                )
                continue

            # Process body rows
            body_rows = raw_table.rows[header_idx + 1 :]
            for row_number, body_row in enumerate(body_rows, start=header_idx + 2):
                if len(body_row) == 0:
                    continue

                # First cell should be prayer name
                prayer_name = body_row[0].strip().lower()
                if prayer_name not in prayer_map:
                    continue

                prayer = prayer_map[prayer_name]

                # Get Iqamah time from the appropriate column
                if iqamah_idx >= len(body_row):
                    continue

                jamaat_raw = body_row[iqamah_idx].strip()
                if not jamaat_raw:
                    continue

                # Parse time
                jamaat_time = coerce_time(jamaat_raw, prayer=prayer.value)
                if jamaat_time is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {jamaat_raw!r}",
                            target_label=self.target_label,
                        )
                    )
                    continue

                # Check plausibility
                window = PLAUSIBLE_WINDOWS.get(prayer.value)
                if window and not (window[0] <= jamaat_time <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{row_date} {prayer.value}: {jamaat_raw!r} outside plausible window",
                            target_label=self.target_label,
                        )
                    )
                    continue

                # Extract successful
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        start_time=None,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label=self.target_label,
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(body_row),
                            selector=f"table row {row_number}",
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
