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
    key = "al_falah_islamic_education_centre_b510ec37"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("alfalahcentre.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        month_name = now.strftime("%B")
        year = now.year
        url = f"https://alfalahcentre.org/{month_name}{year}.pdf"
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

        text = pdf_helpers.extract_text(artifact.body)
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        lines = [line.strip() for line in text.split("\n") if line.strip()]
        now = datetime.now()
        current_month = now.month
        current_year = now.year

        i = 0
        while i < len(lines):
            # Each row should have 14 cells in sequence:
            # [0]=date_num, [1]=islamic_date, [2]=day, [3]=fajr_start, [4]=fajr_jamaat,
            # [5]=sunrise, [6]=dhuhr_start, [7]=dhuhr_jamaat, [8]=asr_start, [9]=asr_jamaat,
            # [10]=maghrib_start, [11]=maghrib_jamaat, [12]=isha_start, [13]=isha_jamaat

            if i + 14 > len(lines):
                break

            cells = lines[i : i + 14]

            try:
                day_num = int(cells[0])
                if day_num < 1 or day_num > 31:
                    i += 1
                    continue

                day_name = cells[2].lower()
                if day_name not in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
                    i += 1
                    continue

                row_date = date(current_year, current_month, day_num)
            except (ValueError, IndexError):
                i += 1
                continue

            prayer_data = {
                Prayer.FAJR: (cells[3], cells[4]),
                Prayer.DHUHR: (cells[6], cells[7]),
                Prayer.ASR: (cells[8], cells[9]),
                Prayer.MAGHRIB: (cells[10], cells[11]),
                Prayer.ISHA: (cells[12], cells[13]),
            }

            for prayer, (start_raw, jamaat_raw) in prayer_data.items():
                if not jamaat_raw or jamaat_raw in ("", "-"):
                    continue

                jamaat = coerce_time(jamaat_raw, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {jamaat_raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue

                start = coerce_time(start_raw, prayer=prayer.value) if start_raw else None
                rows.append(
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
                            raw_text=f"{day_num} {cells[1]} {cells[2]} {jamaat_raw}",
                            selector="PDF text",
                        ),
                    )
                )

            i += 14

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable prayer times in PDF",
            )
        return ExtractorResult(rows=rows, warnings=warnings)
