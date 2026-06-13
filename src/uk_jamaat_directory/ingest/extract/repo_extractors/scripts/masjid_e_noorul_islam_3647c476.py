from __future__ import annotations

from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
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
    key = "masjid_e_noorul_islam_3647c476"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("noorulislambolton.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://noorulislambolton.com/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        tables = html_helpers.extract_tables(artifact.text())

        target_table = None
        for table in tables:
            for row in table.rows:
                text = " ".join(row).lower()
                if "prayer" in text and "begins" in text and "jama" in text:
                    target_table = table
                    break
            if target_table:
                break

        if target_table is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_table",
                        message="prayer table not found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="prayer table not found",
            )

        body = target_table.body()
        header_row_idx = None
        for i, row in enumerate(body):
            if row and row[0].lower().strip() == "prayer":
                header_row_idx = i
                break

        if header_row_idx is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_header",
                        message="prayer header row not found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="prayer header row not found",
            )

        header = [html_helpers.normalize_whitespace(c).lower() for c in body[header_row_idx]]
        mni_col = None
        for i, cell in enumerate(header):
            if "mni" in cell and "jama" in cell:
                mni_col = i
                break

        if mni_col is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_mni_column",
                        message="MNI Jama'ah column not found",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="MNI Jama'ah column not found",
            )

        prayer_map = {
            "fajr": Prayer.FAJR,
            "dhuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        today = datetime.now().date()
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        data_rows = body[header_row_idx + 1 :]
        for row in data_rows:
            cells = [html_helpers.normalize_whitespace(c) for c in row]
            if not cells:
                continue
            prayer_name = cells[0].lower().strip("'").strip()
            prayer = prayer_map.get(prayer_name)
            if prayer is None:
                continue
            if mni_col >= len(cells) or not cells[mni_col]:
                continue

            parsed = coerce_time(cells[mni_col], prayer=prayer.value)
            if parsed is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{today} {prayer.value}: {cells[mni_col]!r}",
                        target_label="timetable",
                    )
                )
                continue

            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=parsed,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join(cells),
                        selector="prayer table row",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=rows, warnings=warnings)
