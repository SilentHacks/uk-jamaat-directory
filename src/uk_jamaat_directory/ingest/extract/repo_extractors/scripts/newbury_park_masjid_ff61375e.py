import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.times import parse_time_loose
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
    key = "newbury_park_masjid_ff61375e"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("newburyparkmasjid.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        self.targets = (
            TargetSpec(
                label="timetable",
                url=f"https://newburyparkmasjid.org.uk/wp-admin/admin-ajax.php?action=get_monthly_timetable&month={now.month}&year={now.year}&display=",
                kind=TargetKind.HTML,
            ),
        )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()

        # Extract table rows using regex (HTML is malformed)
        row_pattern = r"<tr[^>]*>(.*?)</tr>"
        rows_html = re.findall(row_pattern, html, re.DOTALL)

        if not rows_html:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_rows",
                        message="no table rows found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no rows found",
            )

        extracted_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        for row_index, row_html in enumerate(rows_html, start=1):
            cells_pattern = r"<td[^>]*>(.*?)</td>"
            cells = re.findall(cells_pattern, row_html, re.DOTALL)

            if len(cells) < 4:
                continue

            # Clean cell text
            cell_text = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]

            # Parse date from first cell
            parsed_date = parse_date_flexible(cell_text[0], default_year=datetime.now().year)
            if parsed_date is None:
                warnings.append(
                    ExtractorWarning(
                        code="bad_date",
                        message=f"row {row_index} has invalid date '{cell_text[0]}'",
                        target_label="timetable",
                    )
                )
                continue

            # Extract prayer times from column indices
            # Column layout: Date(0), Day(1), Fajr-Begins(2), Fajr-Iqamah(3), Sunrise(4),
            # Zuhr-Begins(5), Zuhr-Iqamah(6), Asr-Begins(7), Asr-Iqamah(8),
            # Maghrib-Begins(9), Maghrib-Iqamah(10), Isha-Begins(11), Isha-Iqamah(12)

            prayer_jamaat_cols = {
                Prayer.FAJR: 3,
                Prayer.DHUHR: 6,
                Prayer.ASR: 8,
                Prayer.MAGHRIB: 10,
                Prayer.ISHA: 12,
            }

            for prayer, col_idx in prayer_jamaat_cols.items():
                if col_idx >= len(cell_text):
                    continue

                jamaat_text = cell_text[col_idx].strip()

                # Skip placeholder times (12:00 am usually indicates no real data)
                if "12:00 am" in jamaat_text or not jamaat_text:
                    continue

                jamaat_time = parse_time_loose(jamaat_text)
                if jamaat_time is None:
                    continue

                # For Jumuah, track session numbers
                session_number = 1
                session_label: str | None = None
                if prayer.value == "jumuah":
                    sessions_today = [
                        r
                        for r in extracted_rows
                        if r.date == parsed_date and r.prayer.value == "jumuah"
                    ]
                    session_number = len(sessions_today) + 1
                    session_label = f"session {session_number}"

                evidence = ctx.evidence(
                    target_label="timetable",
                    extractor_key=self.key,
                    extractor_version=self.version,
                    raw_text=jamaat_text,
                    selector=f"tr:nth-child({row_index}) td:nth-child({col_idx + 1})",
                )

                extracted_rows.append(
                    ExtractorRow(
                        date=parsed_date,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        start_time=None,
                        session_number=session_number,
                        session_label=session_label,
                        timezone=ctx.timezone,
                        evidence=evidence,
                    )
                )

        if not extracted_rows:
            if not warnings:
                warnings.append(
                    ExtractorWarning(
                        code="no_extractable_rows",
                        message="rows parsed but no valid prayer times were extractable",
                        target_label="timetable",
                    )
                )
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no valid prayer times extracted",
            )

        return ExtractorResult(rows=extracted_rows, warnings=warnings)
