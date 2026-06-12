from __future__ import annotations

import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import html_to_text
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "shah_jalal_islamic_centre_and_masjid_d7f9ee0e"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("shahjalalmasjidipswich.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://shahjalalmasjidipswich.co.uk/",
            kind=TargetKind.HTML,
        ),
    )

    _JAMAAT_FIELDS = {
        Prayer.FAJR: r"field-name-field-fajr-jamaat[^>]*>.*?field-item[^>]*>\s*([0-9:.apm\s]+)",
        Prayer.DHUHR: r"field-name-field-dhur-jamaat[^>]*>.*?field-item[^>]*>\s*([0-9:.apm\s]+)",
        Prayer.ASR: r"field-name-field-asr-jamaat[^>]*>.*?field-item[^>]*>\s*([0-9:.apm\s]+)",
        Prayer.MAGHRIB: r"field-name-field-maghrib-jamaat[^>]*>.*?field-item[^>]*>\s*([0-9:.apm\s]+)",
        Prayer.ISHA: r"field-name-field-isha-jamaat[^>]*>.*?field-item[^>]*>\s*([0-9:.apm\s]+)",
    }

    _JUMUAH_PATTERNS = [
        r"Jumm?ua?h?[:\s-]*Friday\s*Jamat[:\s]*([0-9:.apm\s]+)",
        r"Friday\s*Jamat[:\s]*([0-9:.apm\s]+)",
        r"Jumuah[:\s]*([0-9:.apm\s]+)",
    ]

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        text = html_to_text(html)

        jamaat_map: dict[Prayer, date] = {}
        for prayer, pattern in self._JAMAAT_FIELDS.items():
            m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if m:
                raw = m.group(1).strip()
                t = coerce_time(raw, prayer=prayer.value)
                if t is not None:
                    jamaat_map[prayer] = t

        jumuah_time = None
        for pat in self._JUMUAH_PATTERNS:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                raw = m.group(1).strip()
                jt = coerce_time(raw, prayer="jumuah")
                if jt is not None:
                    jumuah_time = jt
                    break

        today = datetime.now().date()
        rows: list[ExtractorRow] = []
        for prayer in (Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA):
            t = jamaat_map.get(prayer)
            if t is None:
                continue
            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=t,
                    start_time=None,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=f"{prayer.value} congregation",
                    ),
                )
            )

        if today.weekday() == 4 and jumuah_time is not None:
            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=Prayer.JUMUAH,
                    jamaat_time=jumuah_time,
                    start_time=None,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text="Jumuah",
                        selector="friday jamaat text",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no jamaat times found")

        return ExtractorResult(rows=rows)
