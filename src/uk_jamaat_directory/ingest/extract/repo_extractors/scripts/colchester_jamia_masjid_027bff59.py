from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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
    key = "colchester_jamia_masjid_027bff59"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("colchestermosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://colchestermosque.co.uk/daily-salah/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        # Date from the visible daily header, e.g. "12 June 2026 <p class=...>26 Dhū..."
        date_match = re.search(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})", html)
        row_date = None
        if date_match:
            row_date = parse_date_flexible(date_match.group(1), default_year=datetime.now().year)
        if row_date is None:
            row_date = datetime.now().date()

        # The daily board table has a "Jama'ah" (or "Jamaah") row with jamaat times
        # in column order corresponding to: Fajr, (Sunrise skipped), Zuhr, Asr, Maghrib, Isha.
        # The rendered HTML is malformed (some <td> closed by </th>); be tolerant.
        jama_row_match = re.search(
            r"<th[^>]*>\s*Jama[^<]*</th>(.*?)</tr>",
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if not jama_row_match:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no jama'ah row found",
            )

        cell_html = jama_row_match.group(1)
        # tolerant: match any <t[dh]...>value</t[dh]> even if tag mismatch
        cells = re.findall(r"<t[dh][^>]*>([^<]*)</t[dh]>", cell_html, re.IGNORECASE)
        time_cells = [c.strip() for c in cells if re.search(r":|\d\s*(?:am|pm)", c, re.IGNORECASE)]
        if len(time_cells) < 5:
            # fallback: collect bare time strings inside the row
            time_cells = re.findall(r"(\d{1,2}:\d{2}\s*(?:am|pm)?)", cell_html, re.IGNORECASE)

        prayer_map = [Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA]
        for prayer, raw in zip(prayer_map, time_cells):
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
            rows.append(
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
                        raw_text=raw,
                        selector="dpt daily jama'ah row",
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
