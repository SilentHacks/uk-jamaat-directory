from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import find_table
from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS, coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
    ExtractorResult,
    ExtractorRow,
    ExtractorWarning,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    TableTimetableExtractor,
)


class Extractor(TableTimetableExtractor):
    key = "jumu_ah_salaah_4c925720"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("becktonislamicassociation.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://becktonislamicassociation.org.uk/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("date", "day", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 3,
        Prayer.DHUHR: 6,
        Prayer.ASR: 8,
        Prayer.MAGHRIB: 10,
        Prayer.ISHA: 12,
    }

    def accept_row(self, row, row_date):
        if not row or len(row) < 13:
            return False
        return row_date is not None

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        table = find_table(artifact.text(), header_keywords=list(self.table_keywords))
        if table is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message=f"no table matching {self.table_keywords}",
                        target_label=self.target_label,
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        warnings = []
        body = [[self.clean_cell(cell) for cell in row] for row in table.body()]
        year = self.current_year(ctx)
        month = self.current_month(ctx)

        jamaat_cols = {
            Prayer.FAJR: 3,
            Prayer.DHUHR: 6,
            Prayer.ASR: 8,
            Prayer.MAGHRIB: 10,
            Prayer.ISHA: 12,
        }

        rows = []
        for row_number, row in enumerate(body, start=1):
            if len(row) < 13:
                continue
            row_date = self.parse_date_cell(row[0], year=year, month=month)
            if row_date is None or not self.accept_row(row, row_date):
                continue

            for prayer, col_idx in jamaat_cols.items():
                raw = row[col_idx] if col_idx < len(row) else ""
                if not raw:
                    continue
                jamaat = coerce_time(raw, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {raw!r}",
                            target_label=self.target_label,
                        )
                    )
                    continue
                window = PLAUSIBLE_WINDOWS.get(prayer.value)
                if window and not (window[0] <= jamaat <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{row_date} {prayer.value}: {raw!r} outside plausible window",
                            target_label=self.target_label,
                        )
                    )
                    continue

                actual_prayer = prayer
                if prayer == Prayer.DHUHR and row_date.weekday() == 4:
                    actual_prayer = Prayer.JUMUAH

                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=actual_prayer,
                        jamaat_time=jamaat,
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

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
