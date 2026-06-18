from datetime import date

from uk_jamaat_directory.domain import Prayer
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
    key = "hitchin_mosque_a6685012"
    version = "2026.06.18.1"
    source_match = SourceMatch(domains=("hitchinmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://hitchinmosque.org/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()

        prayer_map = {
            "fajr": Prayer.FAJR,
            "zuhr": Prayer.DHUHR,
            "dhuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "magrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        # The homepage has a "Namaz | Time" begins-only table AND a
        # [prayer, begins, jamaat] table. We must read the latter: pick, per
        # prayer, the table row that has TWO time cells and use the LAST
        # (jamaat / iqamah). Single-time rows are begins and must be ignored.
        import re as _re

        from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables

        def times_in(cells: list[str]) -> list[str]:
            return [c.strip() for c in cells if _re.search(r"\d{1,2}[:.]\d{2}", c or "")]

        best: dict[Prayer, str] = {}
        for table in extract_tables(html):
            for row_cells in table.body():
                if not row_cells:
                    continue
                prayer = prayer_map.get(row_cells[0].strip().lower())
                if not prayer:
                    continue
                ts = times_in(row_cells[1:])
                # Only trust rows that expose both begins and jamaat (>=2 times);
                # the jamaat/iqamah is the last time on the row.
                if len(ts) >= 2:
                    best[prayer] = ts[-1]

        rows = []
        today = date.today()
        row_number = 0
        for prayer, raw_time in best.items():
            row_number += 1
            jamaat = coerce_time(raw_time, prayer=prayer.value)
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
                        raw_text=f"{prayer.value}: {raw_time}",
                        selector="jamaat (last time) row",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no extractable rows",
            )

        return ExtractorResult(rows=rows)
