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
    key = "blackhall_mosque_cf71f8aa"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("blackhallmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidbox.com/prayer-times/blackhall-mosque-1715251717791",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        full_text = html_to_text(artifact.text())
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        date_pattern = re.compile(
            r"(?P<wd>[A-Za-z]+),\s+(?P<mon>[A-Za-z]{3,9})\s+(?P<d>\d{1,2}),?\s+(?P<y>\d{4})"
        )

        prayer_map = {
            "fajr": Prayer.FAJR,
            "dhuhr": Prayer.DHUHR,
            "zuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        seen: set[tuple] = set()
        for dm in date_pattern.finditer(full_text):
            parsed = parse_date_flexible(dm.group(0), default_year=datetime.now().year)
            if parsed is None:
                continue
            start = dm.end()
            nextm = date_pattern.search(full_text, start)
            end = nextm.start() if nextm else len(full_text)
            block = full_text[start:end]

            jumuah_re = re.compile(
                r"Jumuah\s*(?P<session>\d)?[^\d]*?(?P<h1>\d{1,2})\s*(?P<m1>\d{2})\s*Iqamah\s*(?P<h2>\d{1,2})\s*(?P<m2>\d{2})",
                re.IGNORECASE,
            )
            for jm in jumuah_re.finditer(block):
                if parsed.weekday() != 4:
                    continue
                try:
                    h = int(jm.group("h2"))
                    m = int(jm.group("m2"))
                    jt = coerce_time(f"{h}:{m:02d}", prayer="jumuah")
                    if jt is None:
                        continue
                    win = PLAUSIBLE_WINDOWS.get("jumuah")
                    if win and not (win[0] <= jt <= win[1]):
                        continue
                    session = 1
                    if jm.group("session"):
                        try:
                            session = int(jm.group("session"))
                        except ValueError:
                            session = 1
                    key = (parsed, "jumuah", session)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(
                        ExtractorRow(
                            date=parsed,
                            prayer=Prayer.JUMUAH,
                            jamaat_time=jt,
                            session_number=session,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=jm.group(0),
                                selector="jumuah iqamah",
                            ),
                        )
                    )
                except Exception:
                    continue

            iqamah_re = re.compile(
                r"(?P<label>Fajr|Shuruq|Zuhr|Dhuhr|Asr|Maghrib|Isha)[^\d]*?(?P<h1>\d{1,2})\s*(?P<m1>\d{2})\s*Iqamah\s*(?P<h2>\d{1,2})\s*(?P<m2>\d{2})",
                re.IGNORECASE,
            )
            for m in iqamah_re.finditer(block):
                label = m.group("label").lower()
                if label == "shuruq":
                    continue
                prayer = prayer_map.get(label)
                if not prayer:
                    continue
                try:
                    h = int(m.group("h2"))
                    mi = int(m.group("m2"))
                    jt = coerce_time(f"{h}:{mi:02d}", prayer=prayer.value)
                    if jt is None:
                        continue
                    emitted = (
                        Prayer.JUMUAH
                        if (parsed.weekday() == 4 and prayer == Prayer.DHUHR)
                        else prayer
                    )
                    win = PLAUSIBLE_WINDOWS.get(emitted.value)
                    if win and not (win[0] <= jt <= win[1]):
                        continue
                    key = (parsed, emitted.value, 1)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(
                        ExtractorRow(
                            date=parsed,
                            prayer=emitted,
                            jamaat_time=jt,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=m.group(0),
                                selector=f"iqamah for {label}",
                            ),
                        )
                    )
                except Exception:
                    continue
            # Fallback: two times after label (adhan then iqamah) when "Iqamah" text missing
            for label_key, prayer in prayer_map.items():
                pat = re.compile(
                    rf"{re.escape(label_key)}\s*(\d{{1,2}})\s*(\d{{2}})\s*(\d{{1,2}})\s*(\d{{2}})",
                    re.IGNORECASE,
                )
                for fm in pat.finditer(block):
                    try:
                        h2 = int(fm.group(3))
                        m2 = int(fm.group(4))
                        jt = coerce_time(f"{h2}:{m2:02d}", prayer=prayer.value)
                        if jt is None:
                            continue
                        key = (parsed, prayer.value, 1)
                        if key in seen:
                            continue
                        seen.add(key)
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
                                    raw_text=fm.group(0),
                                    selector=f"fallback iqamah for {label_key}",
                                ),
                            )
                        )
                    except Exception:
                        continue

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable jamaat rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
