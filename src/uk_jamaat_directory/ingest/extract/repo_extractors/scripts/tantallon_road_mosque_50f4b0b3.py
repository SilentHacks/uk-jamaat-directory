from __future__ import annotations

import re
from datetime import date, datetime

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
    key = "tantallon_road_mosque_50f4b0b3"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("jamiaislamiaglasgow.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://jamiaislamiaglasgow.org.uk/32371-2/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        today = datetime.now().date()

        def _map_label(lab: str) -> Prayer | None:
            l = lab.lower()
            if "fajr" in l:
                return Prayer.FAJR
            if "zuhr" in l or "zohr" in l or "dhuhr" in l:
                return Prayer.DHUHR
            if "asr" in l:
                return Prayer.ASR
            if "maghrib" in l or "magrib" in l:
                return Prayer.MAGHRIB
            if "isha" in l or "esha" in l:
                return Prayer.ISHA
            if "jumu" in l or "jumma" in l or "jumah" in l:
                return Prayer.JUMUAH
            return None

        # Primary: parse any tables and look for a prayer/iqamah style one
        tables = html_helpers.extract_tables(html)
        table = None
        for t in tables:
            header_text = " ".join((c or "").lower() for c in t.header)
            if "iqamah" in header_text or ("prayer" in header_text and "begins" in header_text):
                table = t
                break

        if table is not None:
            for r in table.rows:
                if not r:
                    continue
                label = (r[0] or "").strip()
                llow = label.lower()
                if llow in {"prayer", "begins", "iqamah", ""}:
                    continue
                jamaat_raw = ""
                if len(r) > 2:
                    jamaat_raw = (r[2] or "").strip()
                if not jamaat_raw and len(r) > 1:
                    jamaat_raw = (r[1] or "").strip()
                if not jamaat_raw:
                    continue
                prayer = _map_label(label)
                if prayer is None:
                    continue
                jt = coerce_time(jamaat_raw, prayer=prayer.value)
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{today} {label}: {jamaat_raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                window = PLAUSIBLE_WINDOWS.get(prayer.value)
                if window and not (window[0] <= jt <= window[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{today} {prayer.value}: {jamaat_raw!r} outside plausible window",
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
                            raw_text=" | ".join(str(x) for x in r),
                            selector="prayer timetable row",
                        ),
                    )
                )

        if not rows:
            # Robust scrape of the dpt vertical board (the /32371-2/ page renders a single-day
            # table + spans with class dpt_jamah for iqamah and dsJumuah-vertical for Jumuah).
            # We deliberately look for the *Iqamah* value (class dpt_jamah / sc* wrappers).
            prayer_patterns = [
                (r"Fajr", Prayer.FAJR),
                (r"Zuhr|Zohr|Dhuhr", Prayer.DHUHR),
                (r"Asr", Prayer.ASR),
                (r"Maghrib|Magrib", Prayer.MAGHRIB),
                (r"Isha|Esha", Prayer.ISHA),
            ]
            for pat, pr in prayer_patterns:
                # Match a dpt_jamah span that appears after the prayer label in the same table row context
                m = re.search(
                    rf"(?is)<td[^>]*prayerName[^>]*>\s*<span[^>]*>{pat}</span>.*?<td[^>]*>.*?class=[^>]*dpt_jamah[^>]*>\s*<span[^>]*>([0-9]{{1,2}}[:.]?[0-9]{{2}}\s*(?:am|pm)?)</span>",
                    html,
                )
                if not m:
                    # looser: any dpt_jamah value within ~300 chars after the label
                    m = re.search(
                        rf"(?is){pat}.{{0,300}}?class=[^>]*dpt_jamah[^>]*>(?:<span[^>]*>)?([0-9]{{1,2}}[:.]?[0-9]{{2}}\s*(?:am|pm)?)",
                        html,
                    )
                if m:
                    raw = m.group(1).strip()
                    jt = coerce_time(raw, prayer=pr.value)
                    if jt is None:
                        warnings.append(
                            ExtractorWarning(
                                code="unparseable_time",
                                message=f"{today} {pat}: {raw!r}",
                                target_label="timetable",
                            )
                        )
                        continue
                    window = PLAUSIBLE_WINDOWS.get(pr.value)
                    if window and not (window[0] <= jt <= window[1]):
                        warnings.append(
                            ExtractorWarning(
                                code="implausible_time",
                                message=f"{today} {pr.value}: {raw!r} outside plausible window",
                                target_label="timetable",
                            )
                        )
                        continue
                    rows.append(
                        ExtractorRow(
                            date=today,
                            prayer=pr,
                            jamaat_time=jt,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=raw,
                                selector="dpt_jamah",
                            ),
                        )
                    )

            # Jumuah (the vertical board always renders a Jumuah slot with class dsJumuah-vertical)
            if not any(r.prayer == Prayer.JUMUAH for r in rows):
                mj = re.search(
                    r'(?is)class=["\'][^"\']*dsJumuah-vertical[^"\']*["\'][^>]*>([0-9]{1,2}[:.]?[0-9]{2}\s*(?:am|pm)?)<',
                    html,
                )
                if not mj:
                    mj = re.search(
                        r"(?is)Jumuah|Jummah|Jumua[^<]{0,200}?>([0-9]{1,2}[:.]?[0-9]{2}\s*(?:am|pm)?)<",
                        html,
                    )
                if mj:
                    raw = mj.group(1).strip()
                    jt = coerce_time(raw, prayer=Prayer.JUMUAH.value)
                    if jt is None:
                        warnings.append(
                            ExtractorWarning(
                                code="unparseable_time",
                                message=f"{today} Jumuah: {raw!r}",
                                target_label="timetable",
                            )
                        )
                    else:
                        window = PLAUSIBLE_WINDOWS.get(Prayer.JUMUAH.value)
                        if window and not (window[0] <= jt <= window[1]):
                            warnings.append(
                                ExtractorWarning(
                                    code="implausible_time",
                                    message=f"{today} jumuah: {raw!r} outside plausible window",
                                    target_label="timetable",
                                )
                            )
                        else:
                            rows.append(
                                ExtractorRow(
                                    date=today,
                                    prayer=Prayer.JUMUAH,
                                    jamaat_time=jt,
                                    timezone=ctx.timezone,
                                    evidence=ctx.evidence(
                                        target_label="timetable",
                                        extractor_key=self.key,
                                        extractor_version=self.version,
                                        raw_text=raw,
                                        selector="dsJumuah-vertical",
                                    ),
                                )
                            )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
