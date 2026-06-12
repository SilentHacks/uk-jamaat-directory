from __future__ import annotations

import re
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
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
    key = "romford_mosque_39fc1ad0"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("romfordmosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        self.targets = (
            TargetSpec(
                label="timetable",
                url="http://romfordmosque.co.uk/",
                kind=TargetKind.HTML,
            ),
        )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)

        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        today = datetime.now().date()
        date_obj: date | None = None
        sched_block = text

        bm = re.search(r"(?i)Athan", text)
        if bm:
            start = max(0, bm.start() - 400)
            end = min(len(text), bm.end() + 300)
            sched_block = text[start:end]
            for pat, fmt in (
                (
                    r"(?i)(?:[A-Za-z]+day,?\s*)?(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
                    "%d %B %Y",
                ),
                (
                    r"(?i)(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
                    "%B %d %Y",
                ),
            ):
                m = re.search(pat, sched_block)
                if m:
                    try:
                        if fmt.startswith("%d"):
                            ds = f"{m.group(1)} {m.group(2)} {m.group(3)}"
                        else:
                            ds = f"{m.group(1)} {m.group(2)} {m.group(3)}"
                        d = datetime.strptime(ds, fmt).date()
                        if abs((d - today).days) <= 7:
                            date_obj = d
                            break
                    except ValueError:
                        pass
        if date_obj is None:
            for pat, fmt in (
                (
                    r"(?i)(?:[A-Za-z]+day,?\s*)?(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
                    "%d %B %Y",
                ),
                (
                    r"(?i)(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
                    "%B %d %Y",
                ),
            ):
                m = re.search(pat, sched_block)
                if m:
                    try:
                        if fmt.startswith("%d"):
                            ds = f"{m.group(1)} {m.group(2)} {m.group(3)}"
                        else:
                            ds = f"{m.group(1)} {m.group(2)} {m.group(3)}"
                        d = datetime.strptime(ds, fmt).date()
                        if abs((d - today).days) <= 7:
                            date_obj = d
                            break
                    except ValueError:
                        pass
        if date_obj is None:
            date_obj = today

        prayer_map = {
            "fajr": Prayer.FAJR,
            "dhuhr": Prayer.DHUHR,
            "zuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        for label, prayer in prayer_map.items():
            pat = rf"(?i)\b{label}\b[^0-9]*?(\d{{1,2}}[:.]\d{{2}})[^0-9]*?(\d{{1,2}}[:.]\d{{2}})"
            mm = re.search(pat, sched_block)
            if not mm:
                continue
            raw_j = mm.group(2).replace(".", ":")
            jt = coerce_time(raw_j, prayer=prayer.value)
            if jt is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{date_obj} {prayer.value}: {raw_j!r}",
                        target_label="timetable",
                    )
                )
                continue
            rows.append(
                ExtractorRow(
                    date=date_obj,
                    prayer=prayer,
                    jamaat_time=jt,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=f"{label} {mm.group(1)} {mm.group(2)}",
                        selector=f"text {label}",
                    ),
                )
            )

        jm = re.search(
            r"(?i)\bJumu?ah\s*(\d)?[^0-9]*?(\d{1,2}[:.]\d{2})[^0-9]*?(\d{1,2}[:.]\d{2})",
            sched_block,
        )
        if jm:
            sess = int(jm.group(1)) if jm.group(1) and jm.group(1).isdigit() else 1
            raw_j = jm.group(3).replace(".", ":")
            jt = coerce_time(raw_j, prayer="jumuah")
            if jt is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{date_obj} jumuah: {raw_j!r}",
                        target_label="timetable",
                    )
                )
            else:
                rows.append(
                    ExtractorRow(
                        date=date_obj,
                        prayer=Prayer.JUMUAH,
                        jamaat_time=jt,
                        session_number=sess,
                        session_label="Jumuah" if sess == 1 else f"Jumuah {sess}",
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"Jumuah {jm.group(2)} {jm.group(3)}",
                            selector="text jumuah",
                        ),
                    )
                )

        seen = set()
        deduped: list[ExtractorRow] = []
        for r in rows:
            k = (r.date, r.prayer, r.session_number)
            if k in seen:
                continue
            seen.add(k)
            deduped.append(r)
        rows = deduped

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
