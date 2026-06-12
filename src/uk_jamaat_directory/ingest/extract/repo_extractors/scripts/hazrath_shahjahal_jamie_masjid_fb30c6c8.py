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
    key = "hazrath_shahjahal_jamie_masjid_fb30c6c8"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("hsjm.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    targets = (
        TargetSpec(
            label="timetable",
            url="https://prayertime.hsjm.co.uk/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        text = artifact.text()
        table = html_helpers.find_table(text, header_keywords=["prayer", "iqamah"])
        if table is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable table not found",
            )

        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []
        today = datetime.now().date()

        header_lower = [h.lower() for h in table.header]
        try:
            prayer_idx = next(i for i, h in enumerate(header_lower) if "prayer" in h)
        except StopIteration:
            prayer_idx = 0
        try:
            jamaat_idx = next(
                i for i, h in enumerate(header_lower) if "iqamah" in h or "jamah" in h
            )
        except StopIteration:
            jamaat_idx = 2

        prayer_map = {
            "fajr": Prayer.FAJR,
            "dhur": Prayer.DHUHR,
            "zuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        for r in table.rows:
            if not r or len(r) <= max(prayer_idx, jamaat_idx):
                continue
            pname = (r[prayer_idx] or "").strip().lower()
            if "sunrise" in pname or not pname:
                continue
            prayer = prayer_map.get(pname)
            if prayer is None:
                continue
            raw_j = (r[jamaat_idx] or "").strip()
            if not raw_j:
                continue
            jt = coerce_time(raw_j, prayer=prayer.value)
            if jt is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{today} {pname}: {raw_j!r}",
                        target_label="timetable",
                    )
                )
                continue
            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=jt,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join(r),
                        selector="dsPrayerTimetable row",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no jamaat rows extracted",
            )
        return ExtractorResult(rows=rows, warnings=warnings)
