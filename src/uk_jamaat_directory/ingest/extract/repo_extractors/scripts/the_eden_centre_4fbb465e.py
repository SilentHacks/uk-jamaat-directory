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
    key = "the_eden_centre_4fbb465e"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("theedenfoundation.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://theedenfoundation.org.uk/prayer-times",
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

        # Parse visible date header, e.g. "Friday 12 June"
        row_date = None
        date_match = re.search(
            r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
            r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December))",
            text,
            re.IGNORECASE,
        )
        if date_match:
            row_date = parse_date_flexible(date_match.group(1), default_year=datetime.now().year)
        if row_date is None:
            row_date = datetime.now().date()

        # Focus on the schedule region if present
        sched_match = re.search(
            r"Today's Schedule.*?(?:Support Our Mission|Your Generosity|Quick Links|\Z)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        sched = sched_match.group(0) if sched_match else text

        # Label -> Prayer (handle Jumu'ah variants and Dhuhr/Zuhr)
        prayer_map = {
            "fajr": Prayer.FAJR,
            "jumu": Prayer.JUMUAH,
            "dhuhr": Prayer.DHUHR,
            "zuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        # Match patterns like: "Fajr 01:10 Jamaat 04:00" or "Jumu’ah 13:12 Khutbah 13:30"
        # Only emit when an explicit Jamaat/Khutbah value is present (adhan-only rows are skipped).
        card_re = re.compile(
            r"(?P<label>Fajr|Jumu[’']?ah|Dhuhr|Zuhr|Asr|Maghrib|Isha)\s+"
            r"(?P<start>\d{1,2}:\d{2})"
            r"(?:\s*(?P<meta>Jamaat|Khutbah)\s+(?P<j>\d{1,2}:\d{2}))?",
            re.IGNORECASE,
        )

        rows: list[ExtractorRow] = []
        seen = set()
        for m in card_re.finditer(sched):
            lab = m.group("label").lower().rstrip("’'")
            prayer = None
            for prefix, p in prayer_map.items():
                if lab.startswith(prefix):
                    prayer = p
                    break
            if prayer is None:
                continue
            jraw = m.group("j")
            if not jraw:
                # No explicit jamaat/khutbah annotation for this card -> skip (adhan/start only)
                continue
            jt = coerce_time(jraw, prayer=prayer.value)
            if jt is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{row_date} {prayer.value}: {jraw!r}",
                        target_label="timetable",
                    )
                )
                continue
            # Only emit rows inside the global plausible windows (semantics gate is authoritative)
            win = PLAUSIBLE_WINDOWS.get(prayer.value)
            if win and not (win[0] <= jt <= win[1]):
                continue
            # dedupe if any overlap on same (date, prayer)
            dedup_key = (row_date, prayer)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
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
                        raw_text=m.group(0),
                        selector="prayer card",
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
