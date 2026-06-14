from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
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
    key = "southcourt_islamic_centre_5e5a1980"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("southcourtislamiccentre.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    def __init__(self) -> None:
        super().__init__()
        self.targets = (
            TargetSpec(
                label="timetable",
                url="https://southcourtislamiccentre.co.uk/",
                kind=TargetKind.HTML,
            ),
        )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        text = html_helpers.html_to_text(html)

        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []
        today = datetime.now().date()

        # Daily prayers (jamaat/iqamah). Site uses "Dhuhur" spelling.
        prayer_specs: list[tuple[str, Prayer]] = [
            ("Fajr", Prayer.FAJR),
            ("Dhuhur", Prayer.DHUHR),
            ("Asr", Prayer.ASR),
            ("Maghrib", Prayer.MAGHRIB),
            ("Isha", Prayer.ISHA),
        ]

        for label, prayer in prayer_specs:
            # Prefer text form for robustness across elementor layout tweaks
            m = re.search(
                rf"{re.escape(label)}\b[^0-9]*(\d{{1,2}}[:.]\d{{2}}(?:\s*[ap]m)?)",
                text,
                re.IGNORECASE,
            )
            if not m:
                # fallback to raw HTML near the label heading
                m = re.search(
                    rf"{re.escape(label)}[^<]*?</[^>]+>\s*<[^>]+[^>]*>\s*(\d{{1,2}}[:.]\d{{2}}(?:\s*[ap]m)?)",
                    html,
                    re.IGNORECASE | re.DOTALL,
                )
            if not m:
                continue
            raw = m.group(1).strip()
            jt = coerce_time(raw, prayer=prayer.value)
            if jt is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{today} {prayer.value}: {raw!r}",
                        target_label="timetable",
                    )
                )
                continue
            window = PLAUSIBLE_WINDOWS.get(prayer.value)
            if window and not (window[0] <= jt <= window[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"{today} {prayer.value}: {raw!r} outside plausible window",
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
                        raw_text=raw,
                        selector=f"label {label}",
                    ),
                )
            )

        # Jummah sessions (two listed on the homepage banner)
        jumuah_raws: list[str] = []
        for ord_label in ("1st", "2nd", "first", "second"):
            m = re.search(
                rf"{ord_label}\s*Jummah?\b[^0-9]*(\d{{1,2}}[:.]\d{{2}}(?:\s*[ap]m)?)",
                text,
                re.IGNORECASE,
            )
            if not m:
                m = re.search(
                    rf"{ord_label}\s*Jummah?[^<]*?</[^>]+>\s*<[^>]+[^>]*>\s*(\d{{1,2}}[:.]\d{{2}}(?:\s*[ap]m)?)",
                    html,
                    re.IGNORECASE | re.DOTALL,
                )
            if m:
                val = m.group(1).strip()
                if val not in jumuah_raws:
                    jumuah_raws.append(val)

        is_fri = today.weekday() == 4
        for idx, rawj in enumerate(jumuah_raws, start=1):
            jt = coerce_time(rawj, prayer="jumuah")
            if jt is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{today} jumuah: {rawj!r}",
                        target_label="timetable",
                    )
                )
                continue
            win = PLAUSIBLE_WINDOWS.get("jumuah")
            if win and not (win[0] <= jt <= win[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"{today} jumuah: {rawj!r} outside plausible window",
                        target_label="timetable",
                    )
                )
                continue
            if is_fri:
                rows.append(
                    ExtractorRow(
                        date=today,
                        prayer=Prayer.JUMUAH,
                        jamaat_time=jt,
                        session_number=idx,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=rawj,
                            selector=f"jumuah session {idx}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
