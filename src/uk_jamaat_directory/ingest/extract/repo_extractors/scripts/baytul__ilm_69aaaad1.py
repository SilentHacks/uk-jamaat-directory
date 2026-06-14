from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time, PLAUSIBLE_WINDOWS
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
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables


class Extractor(BaseMosqueWebsiteExtractor):
    key = "baytul__ilm_69aaaad1"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("baytulilm.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://baytulilm.com/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no tables found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no tables found",
            )

        # Find table with "Salah" and "Jama'at" headers (skip first row if it's a date colspan)
        table = None
        for t in tables:
            # Check both first row and second row for headers
            for header_row in [t.rows[0], t.rows[1] if len(t.rows) > 1 else None]:
                if header_row is None:
                    continue
                header_lower = [cell.lower() for cell in header_row]
                if "salah" in header_lower and "jama'at" in header_lower:
                    table = t
                    break
            if table:
                break

        if not table:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="no table with Salah/Jama'at columns",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="timetable table not found",
            )

        # Determine header row and body start
        header_lower = [cell.lower() for cell in table.rows[0]]
        if "salah" in header_lower:
            header_idx = 0
            body_start = 1
        else:
            header_idx = 1
            body_start = 2

        header = table.rows[header_idx]
        salah_col = next(i for i, cell in enumerate(header) if "salah" in cell.lower())
        jamaat_col = next(i for i, cell in enumerate(header) if "jama'at" in cell.lower())

        extracted_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        today = date.today()

        for row_idx, row in enumerate(table.rows[body_start:], start=1):
            if len(row) <= max(salah_col, jamaat_col):
                continue

            prayer_name = row[salah_col].strip()
            jamaat_raw = row[jamaat_col].strip()

            if not prayer_name or not jamaat_raw:
                continue

            prayer = parse_prayer_label(prayer_name)
            if prayer is None:
                continue

            jamaat_time = coerce_time(jamaat_raw, prayer=prayer.value)
            if jamaat_time is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{prayer_name}: {jamaat_raw!r}",
                        target_label="timetable",
                    )
                )
                continue

            window = PLAUSIBLE_WINDOWS.get(prayer.value)
            if window and not (window[0] <= jamaat_time <= window[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"{prayer_name}: {jamaat_raw!r} outside plausible window",
                        target_label="timetable",
                    )
                )
                continue

            evidence = ctx.evidence(
                target_label="timetable",
                extractor_key=self.key,
                extractor_version=self.version,
                raw_text=" | ".join(row),
                selector=f"table tr:nth-child({body_start + row_idx})",
            )

            session_number = 1
            session_label: str | None = None
            if prayer.value == "jumuah":
                sessions = [r for r in extracted_rows if r.date == today and r.prayer.value == "jumuah"]
                session_number = len(sessions) + 1
                session_label = f"session {session_number}"

            extracted_rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=jamaat_time,
                    timezone=ctx.timezone,
                    session_number=session_number,
                    session_label=session_label,
                    evidence=evidence,
                )
            )

        if not extracted_rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )

        return ExtractorResult(rows=extracted_rows, warnings=warnings)
