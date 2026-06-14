import re

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractorResult,
    ExtractorRow,
    ExtractorWarning,
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
    key = "al_sunnah_mosque_e02540b7"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("alsunnahmcr.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://alsunnahmcr.org/prayer-times",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 4,
        Prayer.ASR: 5,
        Prayer.MAGHRIB: 6,
        Prayer.ISHA: 7,
    }

    def _extract_iqamah(self, cell: str) -> str:
        """Extract iqamah time from 'HH:MM AMIqm HH:MM AM' format."""
        match = re.search(r"Iqm\s+(\d{1,2}:\d{2}\s+(?:AM|PM))", cell)
        if match:
            return match.group(1)
        return ""

    def _extract_from_table(self, ctx, table):
        """Override to extract iqamah times from concatenated cells."""
        from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS

        header = [cell.strip() for cell in table.header]
        warnings = []

        # Find date column
        date_idx = self._column_index(header, self.date_column)
        if date_idx is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_date_column",
                        message=f"date column {self.date_column!r} not found in {header}",
                        target_label=self.target_label,
                    )
                ],
                no_schedule_reason="date column not found",
            )

        # Find prayer columns
        prayer_idx = {}
        for prayer, spec in self.prayer_columns.items():
            idx = self._column_index(header, spec)
            if idx is None:
                warnings.append(
                    ExtractorWarning(
                        code="missing_prayer_column",
                        message=f"column {spec!r} for {prayer.value} not found",
                        target_label=self.target_label,
                    )
                )
            else:
                prayer_idx[prayer] = idx

        if not prayer_idx:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no prayer columns found",
            )

        body = [[cell.strip() for cell in row] for row in table.body()]
        year = self.current_year(ctx)
        month = self.current_month(ctx)
        rows = []

        for row_number, row in enumerate(body, start=1):
            if date_idx >= len(row):
                continue

            row_date = self.parse_date_cell(row[date_idx], year=year, month=month)
            if row_date is None or not self.accept_row(row, row_date):
                continue

            for prayer, idx in prayer_idx.items():
                if idx >= len(row):
                    continue
                raw = row[idx]
                if not raw:
                    continue

                # Extract iqamah from concatenated format
                jamaat_str = self._extract_iqamah(raw)
                if not jamaat_str:
                    continue

                jamaat = coerce_time(jamaat_str, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {jamaat_str!r}",
                            target_label=self.target_label,
                        )
                    )
                    continue

                window = PLAUSIBLE_WINDOWS.get(prayer.value)
                if window and not (window[0] <= jamaat <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{row_date} {prayer.value}: {jamaat_str!r} outside plausible window",
                            target_label=self.target_label,
                        )
                    )
                    continue

                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        start_time=None,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label=self.target_label,
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(row),
                            selector=f"table row {row_number}",
                        ),
                    )
                )

        return ExtractorResult(
            rows=rows,
            warnings=warnings,
            no_schedule_reason="no extractable rows" if not rows else None,
        )
