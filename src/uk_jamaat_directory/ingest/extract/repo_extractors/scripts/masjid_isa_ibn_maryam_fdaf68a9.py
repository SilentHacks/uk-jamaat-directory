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
    key = "masjid_isa_ibn_maryam_fdaf68a9"
    version = "2026.06.16.1"
    source_match = SourceMatch(domains=("isaibnmaryam.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://isaibnmaryam.co.uk/prayer-time/",
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

        rows = []
        today = date.today()
        prayer_map = {
            "fajr": Prayer.FAJR,
            "zuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        # Try to extract from tables first
        if tables:
            for table in tables:
                body_rows = table.body()
                if len(body_rows) < 2:
                    continue

                header_row = body_rows[0]
                header_lower = [h.lower() for h in header_row]

                has_prayer = any(
                    "fajr" in h or "zuhr" in h or "asr" in h or "maghrib" in h or "isha" in h
                    for h in header_lower
                )
                has_jamaat = any(
                    "jamaa" in h or "jamah" in h or "iqamah" in h for h in header_lower
                )

                if not (has_prayer and has_jamaat):
                    continue

                # Find column indices for jamaat
                jamaat_col = next(
                    (
                        i
                        for i, h in enumerate(header_lower)
                        if "jamaa" in h or "jamah" in h or "iqamah" in h
                    ),
                    None,
                )
                if jamaat_col is None:
                    continue

                row_number = 0
                for row_cells in body_rows[1:]:
                    row_number += 1
                    if not row_cells or len(row_cells) <= jamaat_col:
                        continue

                    # First cell is prayer name
                    prayer_name = (row_cells[0] or "").strip().lower()
                    prayer = prayer_map.get(prayer_name)
                    if not prayer:
                        continue

                    raw_jamaat = (row_cells[jamaat_col] or "").strip()
                    if not raw_jamaat or raw_jamaat.lower() in ("jamaa", "jamah", "iqamah", "time"):
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
                    # Found data, return immediately
                    return ExtractorResult(rows=rows)

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no prayer times found in tables",
            )

        return ExtractorResult(rows=rows)
