from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    BaseMosqueWebsiteExtractor,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "medina_mosque_4ea05a3a"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("medinaicwindsor.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://medinaicwindsor.co.uk/prayer-time/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no tables found",
            )

        rows = []
        today = date.today()
        prayer_map = {
            "fajr": Prayer.FAJR,
            "zuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        for table in tables:
            body_rows = table.body()
            if len(body_rows) < 2:
                continue

            # DPT plugin: first body row is actual header (not table.header)
            header_row = body_rows[0]
            header_lower = [h.lower() for h in header_row]
            
            has_prayer = any("prayer" in h for h in header_lower)
            has_iqamah = any("iqamah" in h or "jamah" in h for h in header_lower)
            
            if not (has_prayer and has_iqamah):
                continue

            # Find column indices
            prayer_col = next((i for i, h in enumerate(header_lower) if "prayer" in h), 0)
            iqamah_col = next((i for i, h in enumerate(header_lower) if "iqamah" in h or "jamah" in h), 2)

            row_number = 0
            for row_cells in body_rows[1:]:
                row_number += 1
                if not row_cells or prayer_col >= len(row_cells):
                    continue

                prayer_name = (row_cells[prayer_col] or "").strip().lower()
                
                if not prayer_name or prayer_name in ("prayer", "sunrise"):
                    continue

                prayer = prayer_map.get(prayer_name)
                if not prayer:
                    continue

                if iqamah_col >= len(row_cells):
                    continue
                    
                raw_jamaat = (row_cells[iqamah_col] or "").strip()
                if not raw_jamaat or raw_jamaat.lower() in ("iqamah", "jamah", "time"):
                    continue

                jamaat = coerce_time(raw_jamaat, prayer=prayer.value)
                if jamaat is None:
                    continue

                rows.append(
                    ExtractorRow(
                        date=today,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(row_cells),
                            selector=f"table row {row_number}",
                        ),
                    )
                )

            if rows:
                break

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no prayer times extracted",
            )

        return ExtractorResult(rows=rows)
