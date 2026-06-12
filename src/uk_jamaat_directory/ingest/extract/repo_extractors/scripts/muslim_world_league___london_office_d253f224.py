from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
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
    key = "muslim_world_league___london_office_d253f224"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("mwllo.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.mwllo.org.uk/screen/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        row_date = datetime.now().date()

        for table in html_helpers.extract_tables(html):
            header_text = " ".join(table.header).lower()
            if (
                "prayer" not in header_text
                and "iqamah" not in header_text
                and "begins" not in header_text
            ):
                continue
            for r in table.rows[1:]:
                if not r:
                    continue
                name_cell = r[0] if len(r) > 0 else ""
                name = re.sub(r"<[^>]+>", " ", name_cell).strip()
                prayer = parse_prayer_label(name)
                if prayer is None:
                    nl = name.lower()
                    if "sunrise" in nl:
                        continue
                    continue
                if prayer == Prayer.JUMUAH:
                    jcell = r[-1] if len(r) > 0 else ""
                    text = re.sub(r"<[^>]+>", " ", jcell)
                    times = [
                        t.strip() for t in re.split(r"\s*\|\s*", text) if t.strip() and ":" in t
                    ]
                    for sidx, t in enumerate(times, 1):
                        jt = coerce_time(t, prayer=Prayer.JUMUAH.value)
                        if jt is None:
                            continue
                        win = PLAUSIBLE_WINDOWS.get(Prayer.JUMUAH.value)
                        if win and not (win[0] <= jt <= win[1]):
                            continue
                        rows.append(
                            ExtractorRow(
                                date=row_date,
                                prayer=Prayer.JUMUAH,
                                jamaat_time=jt,
                                start_time=None,
                                session_number=sidx,
                                timezone=ctx.timezone,
                                evidence=ctx.evidence(
                                    target_label="timetable",
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    raw_text=t,
                                    selector="jumuah cell",
                                ),
                            )
                        )
                    continue
                begin_cell = r[1] if len(r) > 1 else ""
                iq_cell = r[2] if len(r) > 2 else ""
                begins = re.sub(r"<[^>]+>", " ", begin_cell).strip()
                iqamah = re.sub(r"<[^>]+>", " ", iq_cell).strip()
                jamaat = coerce_time(iqamah, prayer=prayer.value)
                if jamaat is None:
                    continue
                window = PLAUSIBLE_WINDOWS.get(prayer.value)
                if window and not (window[0] <= jamaat <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{row_date} {prayer.value}: {iqamah!r} outside plausible window",
                            target_label="timetable",
                        )
                    )
                    continue
                start = coerce_time(begins, prayer=prayer.value) if begins else None
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jamaat,
                        start_time=start,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{name} | {begins} | {iqamah}",
                            selector="prayer table row",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )

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
