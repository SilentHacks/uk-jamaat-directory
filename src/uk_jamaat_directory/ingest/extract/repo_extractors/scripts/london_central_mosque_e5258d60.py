from datetime import datetime
import re

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
    key = "london_central_mosque_e5258d60"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("iccuk.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://timing.athanplus.com/masjid/widgets/embed?theme=2&masjid_id=QKMqqaKB&header=no&monthly=no&iqamahChange=no&showampm=no&labelstart=ADHAN",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        full_text = html_to_text(html)
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        # The widget renders one panel per day in the current window.
        # Each panel starts with an h2 like "Friday, Jun 12, 2026" followed by
        # a table containing ADHAN / IQAMAH (bold in HTML) for the five prayers
        # and a Jumuah line (value repeated in every panel; we emit only on Fridays).
        date_pattern = re.compile(
            r"(?P<wd>[A-Za-z]+),\s+(?P<mon>[A-Za-z]{3,9})\s+(?P<d>\d{1,2}),?\s+(?P<y>\d{4})"
        )

        for m in date_pattern.finditer(full_text):
            date_str = m.group(0)
            parsed = parse_date_flexible(date_str, default_year=datetime.now().year)
            if parsed is None:
                continue
            start = m.end()
            nextm = date_pattern.search(full_text, start)
            end = nextm.start() if nextm else len(full_text)
            block = full_text[start:end]

            def find_second_time(label: str) -> str | None:
                # Matches "Fajr 2:40 3:05" and returns the IQAMAH (second time)
                pat = re.compile(
                    rf"{label}\s+(\d{{1,2}}:\d{{2}}(?:\s*[AP]M)?)\s+(\d{{1,2}}:\d{{2}}(?:\s*[AP]M)?)",
                    re.IGNORECASE,
                )
                mm = pat.search(block)
                if mm:
                    return mm.group(2)
                # Fallback: capture two times after the label anywhere nearby
                mm = re.search(
                    rf"{label}[^0-9]*(\d{{1,2}}:\d{{2}})(?:\s+(\d{{1,2}}:\d{{2}}))?",
                    block,
                    re.IGNORECASE,
                )
                if mm:
                    return mm.group(2) or mm.group(1)
                return None

            for prayer, label in (
                (Prayer.FAJR, "fajr"),
                (Prayer.DHUHR, "dhuhr"),
                (Prayer.ASR, "asr"),
                (Prayer.MAGHRIB, "maghrib"),
                (Prayer.ISHA, "isha"),
            ):
                raw = find_second_time(label)
                if not raw:
                    continue
                jt = coerce_time(raw, prayer=prayer.value)
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{parsed} {prayer.value}: {raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                win = PLAUSIBLE_WINDOWS.get(prayer.value)
                if win and not (win[0] <= jt <= win[1]):
                    continue
                rows.append(
                    ExtractorRow(
                        date=parsed,
                        prayer=prayer,
                        jamaat_time=jt,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=raw,
                            selector=f"iqamah for {label}",
                        ),
                    )
                )

            # Jumuah only on Fridays; the widget repeats the value in every panel.
            if parsed.weekday() == 4:
                j_m = re.search(r"Jumuah[^\d]*(\d{1,2}:\d{2}(?:\s*[AP]M)?)", block, re.IGNORECASE)
                if j_m:
                    jraw = j_m.group(1)
                    jt = coerce_time(jraw, prayer="jumuah")
                    if jt:
                        win = PLAUSIBLE_WINDOWS.get("jumuah")
                        if not win or (win[0] <= jt <= win[1]):
                            rows.append(
                                ExtractorRow(
                                    date=parsed,
                                    prayer=Prayer.JUMUAH,
                                    jamaat_time=jt,
                                    session_number=1,
                                    timezone=ctx.timezone,
                                    evidence=ctx.evidence(
                                        target_label="timetable",
                                        extractor_key=self.key,
                                        extractor_version=self.version,
                                        raw_text=jraw,
                                        selector="jumuah row",
                                    ),
                                )
                            )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
