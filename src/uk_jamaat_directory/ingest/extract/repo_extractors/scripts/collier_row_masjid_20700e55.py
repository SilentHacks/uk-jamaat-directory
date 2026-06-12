from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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
    key = "collier_row_masjid_20700e55"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("collierrowmosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://collierrowmosque.org.uk/timetable/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        text = html_helpers.html_to_text(html)

        # Day heads are of form "Fri 12 Jun - Dhul Hijjah / Muharram 1447"
        # Capture weekday + day + month abbr to delimit blocks and parse date.
        head_pattern = re.compile(
            r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b",
            re.IGNORECASE,
        )

        prayer_map = {
            "fajr": Prayer.FAJR,
            "jumu": Prayer.JUMUAH,
            "jumma": Prayer.JUMUAH,
            "zuhr": Prayer.DHUHR,
            "dhuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        time_re = re.compile(r"(\d{1,2}[:.]\d{2}\s*(?:am|pm)?)", re.IGNORECASE)

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        year = datetime.now().year

        matches = list(head_pattern.finditer(text))
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if (i + 1) < len(matches) else len(text)
            block = text[start:end]

            date_str = f"{m.group(2)} {m.group(3)}"
            d = parse_date_flexible(date_str, default_year=year)
            if d is None:
                continue

            # Find ordered prayer labels inside this day block to bound each row's text.
            label_positions = []
            for lab in prayer_map.keys():
                for lm in re.finditer(rf"(?i)\b{lab}", block):
                    label_positions.append((lm.start(), lab))
            label_positions.sort(key=lambda x: x[0])

            for pos, lab in label_positions:
                prayer = prayer_map[lab]
                # slice from this label to just before the next label (or end of block)
                next_pos = (
                    label_positions[label_positions.index((pos, lab)) + 1][0]
                    if (label_positions.index((pos, lab)) + 1) < len(label_positions)
                    else len(block)
                )
                row_text = block[pos:next_pos]
                times = time_re.findall(row_text)
                if len(times) < 2:
                    continue
                jamaat_raw = times[1].strip()
                if not jamaat_raw:
                    continue
                if jamaat_raw.upper().replace(".", "") in ("N/A", "NA", "N.A"):
                    continue
                jt = coerce_time(jamaat_raw.replace(".", ":"), prayer=prayer.value)
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{d} {prayer.value}: {jamaat_raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                rows.append(
                    ExtractorRow(
                        date=d,
                        prayer=prayer,
                        jamaat_time=jt,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{lab} {jamaat_raw}",
                            selector="prayer_time_row",
                        ),
                    )
                )

        # dedup by (date, prayer, session_number)
        seen = set()
        deduped: list[ExtractorRow] = []
        for r in rows:
            k = (r.date, r.prayer, getattr(r, "session_number", 1))
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
