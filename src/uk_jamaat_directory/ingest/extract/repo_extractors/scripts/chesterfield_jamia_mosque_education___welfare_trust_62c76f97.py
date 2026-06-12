from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
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
    key = "chesterfield_jamia_mosque_education___welfare_trust_62c76f97"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("muslimwelfarechesterfield.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.muslimwelfarechesterfield.com/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        row_date = datetime.now().date()

        prayer_map = {
            "Fajr": Prayer.FAJR,
            "Zuhr": Prayer.DHUHR,
            "Asr": Prayer.ASR,
            "Maghrib": Prayer.MAGHRIB,
            "Isha": Prayer.ISHA,
        }

        for label, prayer in prayer_map.items():
            pat = (
                rf"<span[^>]*>\s*{re.escape(label)}\s*</span>.*?"
                rf'<span[^>]*class=[\'"][^\'"]*dpt_jamah[^\'"]*[\'"][^>]*>([^<]+)</span>'
            )
            m = re.search(pat, html, re.I | re.S)
            if not m:
                continue
            raw = m.group(1).strip()
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
            win = PLAUSIBLE_WINDOWS.get(prayer.value)
            if win and not (win[0] <= jt <= win[1]):
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
                    start_time=None,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=raw,
                        selector=f"time-list3 {label}",
                    ),
                )
            )

        # Jumuah: <span>JUMUAH</span> 1:20 PM <i>Iqamah: 1:30 PM</i>
        ju = re.search(
            r"<span[^>]*>\s*JUMUAH\s*</span>\s*[^<]*?<i[^>]*>\s*Iqamah:\s*([^<]+?)</i>",
            html,
            re.I | re.S,
        )
        if ju:
            jraw = ju.group(1).strip()
            jt = coerce_time(jraw, prayer="jumuah")
            if jt is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{row_date} jumuah: {jraw!r}",
                        target_label="timetable",
                    )
                )
            else:
                win = PLAUSIBLE_WINDOWS.get("jumuah")
                if win and not (win[0] <= jt <= win[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{row_date} jumuah: {jraw!r} outside plausible window",
                            target_label="timetable",
                        )
                    )
                else:
                    rows.append(
                        ExtractorRow(
                            date=row_date,
                            prayer=Prayer.JUMUAH,
                            jamaat_time=jt,
                            start_time=None,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=jraw,
                                selector="JUMUAH iqamah",
                            ),
                        )
                    )

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no extractable rows")

        order = {
            Prayer.FAJR: 0,
            Prayer.DHUHR: 1,
            Prayer.ASR: 2,
            Prayer.MAGHRIB: 3,
            Prayer.ISHA: 4,
            Prayer.JUMUAH: 5,
        }
        rows.sort(key=lambda r: (r.date, order.get(r.prayer, 999), r.session_number))
        return ExtractorResult(rows=rows, warnings=warnings)
