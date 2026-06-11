from datetime import datetime, date
from io import BytesIO

from uk_jamaat_directory.domain import Prayer
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
    key = "telford_central_mosque_f1c1e82a"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("telfordcentralmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        current_month_num = now.month
        current_month_name = now.strftime('%B')
        current_year = now.year

        # The PDF is stored in the previous month's directory
        if current_month_num == 1:
            prev_month_num = 12
            prev_year = current_year - 1
        else:
            prev_month_num = current_month_num - 1
            prev_year = current_year

        url = f"https://www.telfordcentralmosque.com/wp-content/uploads/{prev_year}/{prev_month_num:02d}/{current_month_num:02d}-{current_month_name}-{current_year}.pdf"
        self._targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        all_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        try:
            import pypdf

            reader = pypdf.PdfReader(BytesIO(artifact.body))
            if not reader.pages:
                return ExtractorResult(
                    rows=[],
                    no_schedule_reason="PDF has no pages",
                )

            text = ""
            for page in reader.pages:
                text += page.extract_text()

            now = datetime.now()
            current_year = now.year
            current_month = now.month

            lines = text.split('\n')
            last_day_num = None

            # Process data lines
            for line_idx, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue

                # Skip header lines
                if 'DATE' in line and 'START' in line and 'JAMAT' in line:
                    continue

                # Parse the line
                parts = line.split()
                if len(parts) < 14:
                    continue

                try:
                    # First part should be a row number
                    row_num_str = parts[0]
                    if not row_num_str.isdigit():
                        continue

                    row_num = int(row_num_str)

                    day_name = parts[1].lower()
                    date_str = parts[2]

                    # Check for month transition
                    if not date_str.isdigit():
                        break

                    day_num = int(date_str)

                    # Detect month transition
                    if last_day_num is not None and day_num < last_day_num - 5:
                        break

                    if day_num < 1 or day_num > 31:
                        continue

                    last_day_num = day_num

                    # Validate date for current month
                    try:
                        row_date = date(current_year, current_month, day_num)
                    except ValueError:
                        continue

                    # Validate day of week
                    if day_name not in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
                        continue

                    # Extract prayer times from the split parts
                    # Format: ROW DAY DATE FAJR_START FAJR_JAMAAT SUNRISE DHUHR_START DHUHR_JAMAAT JUMU'AH ASR_START ASR_JAMAAT MAGHRIB ISHA_START ISHA_JAMAAT ...

                    # Fajr jamaat (parts[4])
                    if len(parts) > 4 and parts[4] not in ("]", ""):
                        jamaat = coerce_time(parts[4], prayer=Prayer.FAJR.value)
                        if jamaat:
                            all_rows.append(
                                ExtractorRow(
                                    date=row_date,
                                    prayer=Prayer.FAJR,
                                    jamaat_time=jamaat,
                                    start_time=None,
                                    timezone=ctx.timezone,
                                    evidence=ctx.evidence(
                                        target_label="timetable",
                                        extractor_key=self.key,
                                        extractor_version=self.version,
                                        raw_text=f"Fajr jamaat: {parts[4]}",
                                        selector=f"line {line_idx}",
                                    ),
                                )
                            )

                    # Dhuhr jamaat (parts[7])
                    if len(parts) > 7 and parts[7] not in ("]", ""):
                        jamaat = coerce_time(parts[7], prayer=Prayer.DHUHR.value)
                        if jamaat:
                            all_rows.append(
                                ExtractorRow(
                                    date=row_date,
                                    prayer=Prayer.DHUHR,
                                    jamaat_time=jamaat,
                                    start_time=None,
                                    timezone=ctx.timezone,
                                    evidence=ctx.evidence(
                                        target_label="timetable",
                                        extractor_key=self.key,
                                        extractor_version=self.version,
                                        raw_text=f"Dhuhr jamaat: {parts[7]}",
                                        selector=f"line {line_idx}",
                                    ),
                                )
                            )

                    # Asr jamaat (parts[10])
                    if len(parts) > 10 and parts[10] not in ("]", ""):
                        jamaat = coerce_time(parts[10], prayer=Prayer.ASR.value)
                        if jamaat:
                            all_rows.append(
                                ExtractorRow(
                                    date=row_date,
                                    prayer=Prayer.ASR,
                                    jamaat_time=jamaat,
                                    start_time=None,
                                    timezone=ctx.timezone,
                                    evidence=ctx.evidence(
                                        target_label="timetable",
                                        extractor_key=self.key,
                                        extractor_version=self.version,
                                        raw_text=f"Asr jamaat: {parts[10]}",
                                        selector=f"line {line_idx}",
                                    ),
                                )
                            )

                    # Maghrib (parts[11])
                    if len(parts) > 11 and parts[11] not in ("]", ""):
                        jamaat = coerce_time(parts[11], prayer=Prayer.MAGHRIB.value)
                        if jamaat:
                            all_rows.append(
                                ExtractorRow(
                                    date=row_date,
                                    prayer=Prayer.MAGHRIB,
                                    jamaat_time=jamaat,
                                    start_time=None,
                                    timezone=ctx.timezone,
                                    evidence=ctx.evidence(
                                        target_label="timetable",
                                        extractor_key=self.key,
                                        extractor_version=self.version,
                                        raw_text=f"Maghrib jamaat: {parts[11]}",
                                        selector=f"line {line_idx}",
                                    ),
                                )
                            )

                    # Isha jamaat (parts[13])
                    if len(parts) > 13 and parts[13] not in ("]", ""):
                        jamaat = coerce_time(parts[13], prayer=Prayer.ISHA.value)
                        if jamaat:
                            all_rows.append(
                                ExtractorRow(
                                    date=row_date,
                                    prayer=Prayer.ISHA,
                                    jamaat_time=jamaat,
                                    start_time=None,
                                    timezone=ctx.timezone,
                                    evidence=ctx.evidence(
                                        target_label="timetable",
                                        extractor_key=self.key,
                                        extractor_version=self.version,
                                        raw_text=f"Isha jamaat: {parts[13]}",
                                        selector=f"line {line_idx}",
                                    ),
                                )
                            )

                except (ValueError, IndexError):
                    continue

        except Exception as e:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="pdf_parse_error",
                        message=f"PDF parsing error: {e}",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="PDF parsing error",
            )

        if not all_rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable prayer times",
            )

        return ExtractorResult(rows=all_rows, warnings=warnings)
