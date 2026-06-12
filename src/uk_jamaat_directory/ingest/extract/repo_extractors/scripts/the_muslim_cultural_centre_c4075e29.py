from __future__ import annotations

from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_day_of_month
from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS, coerce_time
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
    key = "the_muslim_cultural_centre_c4075e29"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("gravesendcentralmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://gravesendcentralmosque.com/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = html_helpers.extract_tables(html)

        target_table = None
        for t in tables:
            joined = " ".join(t.rows[0] if t.rows else [])
            if "Prayer Time for" in joined:
                target_table = t
                break
        if target_table is None:
            for t in sorted(tables, key=lambda x: -len(x.rows)):
                if any("Jamat" in " ".join(r) for r in t.rows[:6]):
                    target_table = t
                    break
        if target_table is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no monthly timetable table found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        rows = target_table.rows

        header_row_count = 0
        for i, r in enumerate(rows):
            if r and parse_day_of_month((r[0] or "").strip()) is not None:
                header_row_count = i
                break
        if header_row_count < 2:
            header_row_count = 3

        data_rows = rows[header_row_count:]

        warnings: list[ExtractorWarning] = []
        parsed: list[ExtractorRow] = []
        year = datetime.now().year
        month = datetime.now().month

        prayer_cols = {
            Prayer.FAJR: 2,
            Prayer.DHUHR: 5,
            Prayer.ASR: 7,
            Prayer.MAGHRIB: 9,
            Prayer.ISHA: 11,
        }

        for row_idx, row in enumerate(data_rows, start=header_row_count + 1):
            if not row:
                continue
            day_str = (row[0] or "").strip()
            day = parse_day_of_month(day_str)
            if day is None:
                continue
            try:
                row_date = date(year, month, day)
            except ValueError:
                continue
            for prayer, col in prayer_cols.items():
                if col >= len(row):
                    continue
                raw = (row[col] or "").strip()
                if not raw:
                    continue
                jamaat = coerce_time(raw, prayer=prayer.value)
                if jamaat is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                window = PLAUSIBLE_WINDOWS.get(prayer.value)
                if window and not (window[0] <= jamaat <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{row_date} {prayer.value}: {raw!r} outside plausible window",
                            target_label="timetable",
                        )
                    )
                    continue
                parsed.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        start_time=None,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(row),
                            selector=f"table row {row_idx}",
                        ),
                    )
                )

        if not parsed:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )

        return ExtractorResult(rows=parsed, warnings=warnings)
