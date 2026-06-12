from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.times import (
    PLAUSIBLE_WINDOWS,
    coerce_time,
)
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
    version = "2026.06.12.1"
    source_match = SourceMatch(
        domains=("noorulislambolton.com", "mnibolton.com", "www.mnibolton.com")
    )
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
        html = artifact.text()

        # The homepage carries a daily prayer board with explicit "MNI Jama'ah" times.
        # Date appears in the header e.g. "12th June 2026 | 27 Dhū al-Hijjah 1447".
        date_match = re.search(r"(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+20\d{2})", html, re.IGNORECASE)
        row_date = (
            parse_date_flexible(date_match.group(1), default_year=datetime.now().year)
            if date_match
            else datetime.now().date()
        )
        if row_date is None:
            row_date = datetime.now().date()

        # The MNI Jama'ah values are rendered in spans with class dpt_jamah.
        # The first set of five corresponds to MNI (Fajr, Dhuhr, Asr, Maghrib, Isha).
        jamah_spans = re.findall(r"<span[^>]*dpt_jamah[^>]*>([^<]+)</span>", html, re.IGNORECASE)
        if len(jamah_spans) < 5:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_jamaat_spans",
                        message="expected at least 5 dpt_jamah spans for MNI Jama'ah",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no jamaat times found",
            )

        mni_values = [s.strip() for s in jamah_spans[:5]]
        prayers = [
            Prayer.FAJR,
            Prayer.DHUHR,
            Prayer.ASR,
            Prayer.MAGHRIB,
            Prayer.ISHA,
        ]

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        for prayer, raw in zip(prayers, mni_values):
            jt = coerce_time(raw, prayer=prayer.value)
            if jt is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{row_date} {prayer.value}: {raw!r}",
                        target_label="timetable",
                    )
                )
                continue
            window = PLAUSIBLE_WINDOWS.get(prayer.value)
            if window and not (window[0] <= jt <= window[1]):
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
                    jamaat_time=jt,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=raw,
                        selector="span.dpt_jamah (MNI Jama'ah)",
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
