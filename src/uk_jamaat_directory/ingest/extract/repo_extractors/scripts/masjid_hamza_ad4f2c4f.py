import re
from datetime import datetime, date

from uk_jamaat_directory.domain import Prayer
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
    key = "masjid_hamza_ad4f2c4f"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("masjidehamza.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)

    def __init__(self):
        super().__init__()
        month = datetime.now().month
        self._targets = (
            TargetSpec(
                label="timetable",
                url=f"http://masjidehamza.co.uk/namaztimetable.php?month={month}",
                kind=TargetKind.HTML,
            ),
        )

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = (
            artifact.body.decode("utf-8", errors="ignore")
            if isinstance(artifact.body, bytes)
            else artifact.body
        )
        rows: list[ExtractorRow] = []

        # Find all <tr> elements containing prayer times
        # Pattern: <tr ...><td ...>(\d+)</td> (date) followed by time cells
        tr_pattern = r"<tr[^>]*>.*?</tr>"
        tr_matches = list(re.finditer(tr_pattern, html, re.DOTALL))

        current_year = datetime.now().year
        current_month = datetime.now().month

        for tr_match in tr_matches:
            tr_html = tr_match.group(0)

            # Extract all <td> contents
            td_pattern = r"<td[^>]*>(.*?)</td>"
            td_matches = re.findall(td_pattern, tr_html, re.DOTALL)

            if not td_matches or len(td_matches) < 12:
                continue

            # Clean cell contents
            cells = []
            for td in td_matches:
                # Remove HTML tags and normalize
                cell_text = re.sub(r"<[^>]+>", "", td)
                cell_text = cell_text.strip().replace("&nbsp;", "").strip()
                cells.append(cell_text)

            # First cell should be a date (1-31)
            try:
                day_num = int(cells[0])
                if day_num < 1 or day_num > 31:
                    continue
            except (ValueError, IndexError):
                continue

            # Extract prayer times from fixed column indices
            # Columns: Date | FajrStart | FajrJamat | SunRise | ZuhrStart | ZuhrJamat |
            #          AsrStart | AsrJamat | MaghribStart | MaghribJamat | IshaStart | IshaJamat
            try:
                fajr_time = coerce_time(cells[2], prayer=Prayer.FAJR)
                dhuhr_time = coerce_time(cells[5], prayer=Prayer.DHUHR)
                asr_time = coerce_time(cells[7], prayer=Prayer.ASR)
                maghrib_time = coerce_time(cells[9], prayer=Prayer.MAGHRIB)
                isha_time = coerce_time(cells[11], prayer=Prayer.ISHA)
            except (ValueError, IndexError):
                continue

            # Build prayer time rows
            row_date = date(current_year, current_month, day_num)

            if fajr_time:
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=Prayer.FAJR,
                        jamaat_time=fajr_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{day_num} Fajr {fajr_time}",
                        ),
                    )
                )
            if dhuhr_time:
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=Prayer.DHUHR,
                        jamaat_time=dhuhr_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{day_num} Dhuhr {dhuhr_time}",
                        ),
                    )
                )
            if asr_time:
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=Prayer.ASR,
                        jamaat_time=asr_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{day_num} Asr {asr_time}",
                        ),
                    )
                )
            if maghrib_time:
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=Prayer.MAGHRIB,
                        jamaat_time=maghrib_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{day_num} Maghrib {maghrib_time}",
                        ),
                    )
                )
            if isha_time:
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=Prayer.ISHA,
                        jamaat_time=isha_time,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{day_num} Isha {isha_time}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no prayer times found",
            )

        return ExtractorResult(rows=rows)
