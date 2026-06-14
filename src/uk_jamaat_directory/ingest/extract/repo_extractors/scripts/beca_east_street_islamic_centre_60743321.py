import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
from uk_jamaat_directory.ingest.extract.helpers.html import html_to_text
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
    key = "beca_east_street_islamic_centre_60743321"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("becamasjid.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://becamasjid.org/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        text = html_to_text(html)
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        # The page is a JS-rendered SPA. Default view shows the current day's
        # prayer cards with "begins" + "Jamā'ah" (iqamah) times. We parse the
        # visible text for the iqamah values. A date header may be present;
        # fall back to the run date for the snapshot day.

        def _find_iqamah(block: str, label: str) -> str | None:
            # Prefer explicit "Jamā'ah" following the label.
            pat = re.compile(
                rf"{label}[^J]*Jamā['’]?ah[^0-9]*(\d{{1,2}}:\d{{2}}(?:\s*[AP]M)?)",
                re.IGNORECASE,
            )
            m = pat.search(block)
            if m:
                return m.group(1)
            # Two times after label: second is iqamah.
            m = re.search(
                rf"{label}[^0-9]*(\d{{1,2}}:\d{{2}}(?:\s*[AP]M)?)\s+(\d{{1,2}}:\d{{2}}(?:\s*[AP]M)?)",
                block,
                re.IGNORECASE,
            )
            if m:
                return m.group(2)
            # Fallback: first/only time after label.
            m = re.search(
                rf"{label}[^0-9]*(\d{{1,2}}:\d{{2}}(?:\s*[AP]M)?)",
                block,
                re.IGNORECASE,
            )
            return m.group(1) if m else None

        # Try to parse a date from visible text (e.g. "12 June 2026" or "Fri 12 Jun").
        date = None
        date_pat = re.compile(
            r"(?P<wd>[A-Za-z]+)?,?\s*(?P<d>\d{1,2})\s+(?P<mon>[A-Za-z]{3,9})\s*,?\s*(?P<y>\d{4})?"
        )
        dm = date_pat.search(text)
        if dm:
            parsed = parse_date_flexible(dm.group(0), default_year=datetime.now().year)
            if parsed is not None:
                date = parsed
        if date is None:
            date = datetime.now().date()

        prayer_labels = [
            (Prayer.FAJR, "fajr"),
            (Prayer.DHUHR, "dhuhr"),
            (Prayer.ASR, "asr"),
            (Prayer.MAGHRIB, "maghrib"),
            (Prayer.ISHA, "isha"),
        ]

        for prayer, label in prayer_labels:
            raw = _find_iqamah(text, label)
            if not raw:
                continue
            jt = coerce_time(raw, prayer=prayer.value)
            if jt is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{date} {prayer.value}: {raw!r}",
                        target_label="timetable",
                    )
                )
                continue
            win = PLAUSIBLE_WINDOWS.get(prayer.value)
            if win and not (win[0] <= jt <= win[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"{date} {prayer.value}: {raw!r} outside plausible window",
                        target_label="timetable",
                    )
                )
                continue
            rows.append(
                ExtractorRow(
                    date=date,
                    prayer=prayer,
                    jamaat_time=jt,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=raw,
                        selector=f"jamaat for {label}",
                    ),
                )
            )

        # Jumu'ah blocks appear on Fridays with their own "Jamā'ah" time(s).
        if date.weekday() == 4:
            jpat = re.compile(
                r"Jumu['’]?ah[^0-9]*(\d{1,2}:\d{2}(?:\s*[AP]M)?)",
                re.IGNORECASE,
            )
            for idx, jm in enumerate(jpat.finditer(text), start=1):
                jraw = jm.group(1)
                jt = coerce_time(jraw, prayer="jumuah")
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{date} jumuah[{idx}]: {jraw!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                win = PLAUSIBLE_WINDOWS.get("jumuah")
                if win and not (win[0] <= jt <= win[1]):
                    continue
                rows.append(
                    ExtractorRow(
                        date=date,
                        prayer=Prayer.JUMUAH,
                        jamaat_time=jt,
                        session_number=idx,
                        session_label=f"session {idx}",
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=jraw,
                            selector=f"jumuah iqamah {idx}",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
