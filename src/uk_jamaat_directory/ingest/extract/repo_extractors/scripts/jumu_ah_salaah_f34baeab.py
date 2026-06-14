from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import dates, times
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    CONTRACT_ID,
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
    TableTimetableExtractor,
)


class Extractor(TableTimetableExtractor):
    key = "jumu_ah_salaah_f34baeab"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("cambournecrescent.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://cambournecrescent.org/salah/v2/time-cc-today-v2.php",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("prayer", "start")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 1,
        Prayer.DHUHR: 1,
        Prayer.ASR: 1,
        Prayer.MAGHRIB: 1,
        Prayer.ISHA: 1,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        from bs4 import BeautifulSoup

        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        soup = BeautifulSoup(artifact.body, "html.parser")
        table = soup.find("table", class_="table")

        if not table:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")

        rows = []
        current_date = None
        year = datetime.now().year

        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue

            cell_texts = [c.get_text(strip=True) for c in cells]
            first_cell = cell_texts[0].lower()

            # Check for date row (has day name)
            if any(
                day in first_cell
                for day in [
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                    "saturday",
                    "sunday",
                ]
            ):
                current_date = dates.parse_date_flexible(cell_texts[0], default_year=year)
                continue

            # Check for prayer row
            if first_cell in ("fajr", "dhuhr", "asr", "maghrib", "isha"):
                if not current_date or len(cell_texts) < 3:
                    continue

                prayer = Prayer[first_cell.upper()]
                start_time_str = cell_texts[1]
                jamaat_time_str = cell_texts[2] if len(cell_texts) > 2 else ""

                start_time = times.coerce_time(start_time_str) if start_time_str else None
                jamaat_time = times.coerce_time(jamaat_time_str) if jamaat_time_str else None

                if not start_time:
                    continue

                # Use jamaat time as primary (required field), or start time as fallback
                jamaat_time_to_use = jamaat_time if jamaat_time else start_time

                evidence = ExtractorEvidence(
                    target_label=artifact.target_label,
                    target_url=artifact.target_url,
                    extractor_key=self.key,
                    extractor_version=self.version,
                    contract=CONTRACT_ID,
                )

                rows.append(
                    ExtractorRow(
                        date=current_date,
                        prayer=prayer,
                        jamaat_time=jamaat_time_to_use,
                        start_time=start_time if jamaat_time else None,
                        evidence=evidence,
                    )
                )

        return ExtractorResult(rows=rows)
