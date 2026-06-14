import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
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
    key = "jamiatul_ilm_wal_huda_uk_3bc09b7b"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("jamiah.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        year = datetime.now().year
        month = datetime.now().month
        pdf_url = f"https://www.jamiah.co.uk/wp-content/uploads/jamiah/salah-times/salah-timetable-{year:04d}-{month:02d}.pdf"
        self.targets = (
            TargetSpec(
                label="timetable",
                url=pdf_url,
                kind=TargetKind.PDF,
            ),
        )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        text = pdf_helpers.extract_text(artifact.body)
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        year = datetime.now().year
        month = datetime.now().month

        idx = 0
        while idx < len(lines):
            line = lines[idx]

            day_of_week = line
            if day_of_week not in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
                idx += 1
                continue

            if idx + 12 >= len(lines):
                break

            day_str = lines[idx + 1]
            day_match = re.match(r"(\d+)", day_str)
            if not day_match:
                idx += 1
                continue

            try:
                day = int(day_match.group(1))
                row_date = date(year, month, day)
            except (ValueError, IndexError):
                idx += 1
                continue

            # Extract the 11 time values for this row:
            # Fajr_begin Sunrise Zohar_begin Asar_begin Magrib_begin Isha_begin Fajr_jamaat Zohar_jamaat Asar_jamaat Magrib_jamaat Isha_jamaat
            values = [lines[idx + i] for i in range(2, 13)]

            # Map prayer to its jamaat time index in the values array (0-indexed)
            # values[0] = Fajr begin, values[1] = Sunrise, values[2] = Zohar begin, values[3] = Asar begin,
            # values[4] = Magrib begin, values[5] = Isha begin, values[6] = Fajr jamaat, values[7] = Zohar jamaat,
            # values[8] = Asar jamaat, values[9] = Magrib jamaat, values[10] = Isha jamaat
            prayer_jamaat_indices = {
                Prayer.FAJR: 6,
                Prayer.DHUHR: 7,
                Prayer.ASR: 8,
                Prayer.MAGHRIB: 9,
                Prayer.ISHA: 10,
            }

            for prayer, val_idx in prayer_jamaat_indices.items():
                if val_idx >= len(values):
                    continue

                raw_time = values[val_idx].strip()
                if not raw_time:
                    continue

                jamaat_time = coerce_time(raw_time, prayer=prayer.value)
                if jamaat_time is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {raw_time!r}",
                            target_label="timetable",
                        )
                    )
                    continue

                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        start_time=None,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{day_of_week} {day_str} {' '.join(values)}",
                            selector=f"line {idx}",
                        ),
                    )
                )

            idx += 13

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows from PDF text",
            )

        return ExtractorResult(rows=rows, warnings=warnings)
