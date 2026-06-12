from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import pdf as pdf_helpers
from uk_jamaat_directory.ingest.extract.helpers.rows import carry_forward
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


MONTH_NAMES = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def _clean_carry_marker(value: str) -> str:
    cleaned = value.strip()
    if cleaned in ('" "', '"', "''", "\u201c", "\u201d", "\u201e", "-", "—"):
        return ""
    return cleaned


class Extractor(BaseMosqueWebsiteExtractor):
    key = "masjid_adam_5d5ccd86"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("masjidadam.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        month_name = MONTH_NAMES[now.month]
        url = (
            f"https://masjidadam.co.uk/wp-content/uploads/"
            f"{now.year}/{now.month:02d}/{month_name}-{now.year}_compressed.pdf"
        )
        self._targets = (
            TargetSpec(
                label="timetable",
                url=url,
                kind=TargetKind.PDF,
                requires_pdf=True,
            ),
        )

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self._targets

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        # Use word positions for reliable left/right column separation (tables not detected)
        try:
            doc = pdf_helpers.open_pdf(artifact.body)
            page = doc[0]
            words = page.get_text("words")
            doc.close()
        except Exception as exc:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="pdf_open_error",
                        message=f"failed to open/parse PDF: {exc}",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="failed to open PDF",
            )

        # Group words by approximate y for line reconstruction
        lines: dict[int, list[tuple[float, str]]] = defaultdict(list)
        for w in words:
            yk = round(w[1])
            lines[yk].append((w[0], w[4]))
        ordered: list[tuple[int, list[tuple[float, str]]]] = []
        for y in sorted(lines.keys()):
            its = sorted(lines[y], key=lambda t: t[0])
            ordered.append((y, its))

        now = datetime.now()
        year = now.year
        month = now.month

        day_to_jamaat: dict[int, list[str]] = {}
        PRAYERS = [Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA]

        DAY_TRIGRAMS = {"mon", "tues", "wed", "thur", "fri", "sat", "sun"}

        # Find day rows by presence of weekday name; parse day num from same or nearby line,
        # and associate with the nearest upward time-bearing line.
        for i, (_y, items) in enumerate(ordered):
            joined = " ".join(t.lower() for _x, t in items)
            if not any(trig in joined for trig in DAY_TRIGRAMS):
                continue
            # Find day number: prefer left side of this line, else scan upward a few lines
            day = None
            for x, tok in items:
                if tok.isdigit():
                    dn = int(tok)
                    if 1 <= dn <= 31:
                        day = dn
                        break
            if day is None:
                for j in range(i - 1, max(-1, i - 4), -1):
                    _py, pitems = ordered[j]
                    for x, tok in pitems[:3]:
                        if tok.isdigit():
                            dn = int(tok)
                            if 1 <= dn <= 31:
                                day = dn
                                break
                    if day is not None:
                        break
            if day is None:
                continue

            # Find nearest upward line that has colon time tokens (the times row)
            time_items: list[tuple[float, str]] | None = None
            for j in range(i - 1, max(-1, i - 6), -1):
                _py, pitems = ordered[j]
                pjoined = " ".join(t for _x, t in pitems)
                if re.search(r"\d{1,2}:\d{2}", pjoined):
                    time_items = pitems
                    break
            if not time_items:
                continue

            # Rightmost 5 time-or-carry tokens on the time line are the JAMA'AH columns
            tq: list[tuple[float, str]] = []
            for x, t in time_items:
                if (
                    re.match(r"^\d{1,2}:\d{2}$", t)
                    or t in ("“", "”", '"', "''", "„", "—", "-")
                    or re.match(r"^\d{1,2}:\d{2}\s*[AP]?M?$", t, re.IGNORECASE)
                ):
                    tq.append((x, t))
            tq.sort(key=lambda tt: tt[0])
            jamaat_raw = [t for _x, t in tq[-5:]] if len(tq) >= 5 else []
            if jamaat_raw:
                # last one wins if duplicate day detection
                day_to_jamaat[day] = jamaat_raw

        if day_to_jamaat:
            days_sorted = sorted(day_to_jamaat.keys())
            # Build per-column lists, clean carry markers, carry-forward
            cols: list[list[str]] = [[] for _ in range(5)]
            for d in days_sorted:
                raw5 = day_to_jamaat.get(d, [])
                for c in range(5):
                    val = raw5[c] if c < len(raw5) else ""
                    cols[c].append(_clean_carry_marker(val))
            carried = [carry_forward(list(c)) for c in cols]
            for idx, d in enumerate(days_sorted):
                try:
                    rd = date(year, month, d)
                except ValueError:
                    continue
                for pi, prayer in enumerate(PRAYERS):
                    raw = carried[pi][idx] if pi < len(carried) else ""
                    if not raw:
                        continue
                    jt = coerce_time(raw, prayer=prayer.value)
                    if jt is None:
                        warnings.append(
                            ExtractorWarning(
                                code="unparseable_time",
                                message=f"{rd} {prayer.value}: {raw!r}",
                                target_label="timetable",
                            )
                        )
                        continue
                    rows.append(
                        ExtractorRow(
                            date=rd,
                            prayer=prayer,
                            jamaat_time=jt,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=raw,
                                selector=f"day {d}",
                            ),
                        )
                    )

        # Jumuah sessions (always from footer text; apply to Fridays present in month)
        full_text = pdf_helpers.extract_text(artifact.body) or ""
        jumuah_raws: list[str] = []
        jsec = re.search(
            r"JUMMA\s*TIMES(.+?)(?:GET PRAYER|JAMAT TIMES MAY BE|$)",
            full_text,
            re.IGNORECASE | re.DOTALL,
        )
        section = jsec.group(1) if jsec else full_text
        for m in re.finditer(r"(\d{1,2}:\d{2})\s*(AM|PM)", section, re.IGNORECASE):
            jumuah_raws.append(f"{m.group(1)} {m.group(2)}")
            if len(jumuah_raws) >= 3:
                break
        if not jumuah_raws:
            for m in re.finditer(r"(\d{1,2}:\d{2})\s*(AM|PM)", full_text, re.IGNORECASE):
                jumuah_raws.append(f"{m.group(1)} {m.group(2)}")
                if len(jumuah_raws) >= 3:
                    break
        jumuah_times: list = []
        for rawj in jumuah_raws[:3]:
            jt = coerce_time(rawj, prayer=Prayer.JUMUAH.value)
            if jt is None:
                jt = coerce_time(rawj, prayer=Prayer.DHUHR.value)
            if jt:
                jumuah_times.append(jt)

        if jumuah_times:
            fridays: list[date] = []
            for dnum in range(1, 32):
                try:
                    dd = date(year, month, dnum)
                except ValueError:
                    continue
                if dd.weekday() == 4:
                    fridays.append(dd)
            labels = ["1st Jumma", "2nd Jumma", "3rd Jumma"]
            for f in fridays:
                for sidx, jt in enumerate(jumuah_times, start=1):
                    raw_used = jumuah_raws[sidx - 1] if sidx - 1 < len(jumuah_raws) else ""
                    rows.append(
                        ExtractorRow(
                            date=f,
                            prayer=Prayer.JUMUAH,
                            jamaat_time=jt,
                            session_number=sidx,
                            session_label=labels[sidx - 1] if (sidx - 1) < len(labels) else None,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"JUMMA {sidx}: {raw_used}",
                                selector="JUMMA TIMES footer",
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
