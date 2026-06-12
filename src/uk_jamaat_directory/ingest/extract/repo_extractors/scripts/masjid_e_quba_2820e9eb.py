from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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
    key = "masjid_e_quba_2820e9eb"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("masjidquba.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://masjidquba.org/salaah-times/",
            kind=TargetKind.HTML,
        ),
    )

    # Column order inside each monthly time row (after stripping tags):
    # [0]=Day, [1]=Fajar begin, [2]=Sunrise, [3]=Zohr begin, [4]=Asr begin,
    # [5]=Magrib, [6]=Isha begin, [7]=Fajar jamaat, [8]=Zohr jamaat,
    # [9]=Asr jamaat, [10]=Isha jamaat
    _JAMAAT_COLS: dict[Prayer, int] = {
        Prayer.FAJR: 7,
        Prayer.DHUHR: 8,
        Prayer.ASR: 9,
        Prayer.MAGHRIB: 5,  # source publishes same value for maghrib jamaat as start
        Prayer.ISHA: 10,
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        # Locate the monthly timetable block (broadest view on the page)
        month_match = re.search(
            r'id=["\']masjidQuba-Timetable-month["\'].*?<ul class=["\']timetable["\']>(.*?)</ul>\s*</div>',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if not month_match:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_monthly_timetable",
                        message="could not find monthly timetable block",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="monthly timetable not found",
            )

        block = month_match.group(1)
        year = datetime.now().year

        # Find all time rows inside the monthly block
        time_row_matches = re.finditer(
            r'<li class=["\']time[^"\']*["\'][^>]*>(.*?)</ul>\s*</li>',
            block,
            re.IGNORECASE | re.DOTALL,
        )

        for tm in time_row_matches:
            inner = tm.group(1)
            # Extract the <li>...</li> values inside this row
            lis = re.findall(r"<li[^>]*>(.*?)</li>", inner, re.IGNORECASE | re.DOTALL)
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in lis]
            if not cells:
                continue

            date_cell = cells[0]
            row_date = parse_date_flexible(date_cell, default_year=year)
            if row_date is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_date",
                        message=f"could not parse date cell {date_cell!r}",
                        target_label="timetable",
                    )
                )
                continue

            for prayer, col in self._JAMAAT_COLS.items():
                if col >= len(cells):
                    continue
                raw = cells[col]
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
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(cells),
                            selector="monthly timetable row",
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
