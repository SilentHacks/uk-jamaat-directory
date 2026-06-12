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
    if cleaned in ('" "', '"', "''", "\u201c", "\u201d", "\u201e", "-", "—", "]", "[", "„"):
        return ""
    if cleaned in {"\xa0", "\u00a0"} or not cleaned:
        return ""
    return cleaned


class Extractor(BaseMosqueWebsiteExtractor):
    key = "telford_central_mosque_f1c1e82a"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("telfordcentralmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)

    def __init__(self) -> None:
        super().__init__()
        now = datetime.now()
        y = now.year
        m = now.month
        # Current month's timetable is uploaded under previous month folder,
        # filename uses 0-padded target month number as prefix (e.g. 06-June-2026.pdf in /05/).
        folder_y = y if m > 1 else y - 1
        folder_m = m - 1 if m > 1 else 12
        month_name = MONTH_NAMES[m]
        day_prefix = f"{m:02d}"
        url = (
            f"https://www.telfordcentralmosque.com/wp-content/uploads/"
            f"{folder_y}/{folder_m:02d}/{day_prefix}-{month_name}-{y}.pdf"
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

        try:
            doc = pdf_helpers.open_pdf(artifact.body)
            page = doc[0]
            words = page.get_text("words")
            full_text = page.get_text() or ""
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

        # Group words by approximate y to reconstruct per-line tokens (in x order)
        lines_dict: dict[int, list[tuple[float, str]]] = defaultdict(list)
        for w in words:
            yk = round(w[1])
            lines_dict[yk].append((w[0], w[4]))
        ordered: list[tuple[int, list[tuple[float, str]]]] = []
        for y in sorted(lines_dict.keys()):
            its = sorted(lines_dict[y], key=lambda t: t[0])
            ordered.append((y, its))

        now = datetime.now()
        year = now.year
        month = now.month

        PRAYERS_5 = [Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA]
        DAY_TRIGRAMS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}

        day_to_jamaat: dict[int, list[str]] = {}
        day_to_weekday: dict[int, str] = {}

        for _y, items in ordered:
            joined_lower = " ".join(t.lower() for _x, t in items)
            if not any(trig in joined_lower for trig in DAY_TRIGRAMS):
                continue
            day: int | None = None
            wd: str | None = None
            for x, tok in items:
                tl = tok.lower().strip()
                if tl in DAY_TRIGRAMS:
                    wd = tl
                if day is None and tok.isdigit():
                    dn = int(tok)
                    if 1 <= dn <= 31:
                        day = dn
            if day is None:
                continue
            # Collect time and carry tokens present on this line
            time_tokens: list[str] = []
            for x, t in items:
                ts = t.strip()
                if (
                    re.match(r"^\d{1,2}:\d{2}$", ts)
                    or ts in {"]", "[", '"', "''", "\u201c", "\u201d", "\u201e", "„", "—", "-"}
                    or re.match(r"^\d{1,2}:\d{2}", ts)
                ):
                    time_tokens.append(ts)
            if len(time_tokens) < 5:
                continue
            # The 5 jamaat-ish values (4 carryable jamaats + maghrib start used as jamaat):
            # positions in the ~10 time tokens: 1=fajr_j, 4=zuhr_j, 6=asr_j, 7=maghrib_start, 9=isha_j
            jamaat_raw = ["", "", "", "", ""]
            if len(time_tokens) > 1:
                jamaat_raw[0] = time_tokens[1]
            if len(time_tokens) > 4:
                jamaat_raw[1] = time_tokens[4]
            if len(time_tokens) > 6:
                jamaat_raw[2] = time_tokens[6]
            if len(time_tokens) > 7:
                jamaat_raw[3] = time_tokens[
                    7
                ]  # Maghrib: use start time as jamaat (no separate j listed)
            if len(time_tokens) > 9:
                jamaat_raw[4] = time_tokens[9]
            day_to_jamaat[day] = jamaat_raw
            if wd:
                day_to_weekday[day] = wd

        if day_to_jamaat:
            days_sorted = sorted(day_to_jamaat.keys())
            cols: list[list[str]] = [[] for _ in range(5)]
            for d in days_sorted:
                raw5 = day_to_jamaat.get(d, [""] * 5)
                for c in range(5):
                    val = raw5[c] if c < len(raw5) else ""
                    cols[c].append(_clean_carry_marker(val))
            carried = [carry_forward(list(c)) for c in cols]
            for idx, d in enumerate(days_sorted):
                try:
                    rd = date(year, month, d)
                except ValueError:
                    continue
                is_fri = day_to_weekday.get(d, "").startswith("fri")
                for pi, prayer in enumerate(PRAYERS_5):
                    raw = carried[pi][idx] if pi < len(carried) else ""
                    if not raw:
                        continue
                    use_prayer = prayer
                    sess = 1
                    sess_label: str | None = None
                    if is_fri and prayer == Prayer.DHUHR:
                        use_prayer = Prayer.JUMUAH
                        sess = 1
                        sess_label = "1st Jumma"
                    jt = coerce_time(raw, prayer=use_prayer.value)
                    if jt is None:
                        warnings.append(
                            ExtractorWarning(
                                code="unparseable_time",
                                message=f"{rd} {use_prayer.value}: {raw!r}",
                                target_label="timetable",
                            )
                        )
                        continue
                    rows.append(
                        ExtractorRow(
                            date=rd,
                            prayer=use_prayer,
                            jamaat_time=jt,
                            session_number=sess,
                            session_label=sess_label,
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

        # Add 2nd Jumuah session for every Friday from the footer text
        jumuah2_raw: str | None = None
        m2 = re.search(
            r"(?:Second|2nd)\s*(?:Jamat|Jumuah|Jumma|Jumu\'ah)[^\d]*(\d{1,2}:\d{2})",
            full_text,
            re.IGNORECASE,
        )
        if m2:
            jumuah2_raw = m2.group(1)
        else:
            cands = re.findall(r"(\d{1,2}:\d{2})", full_text)
            plausible: list[str] = []
            for c in cands:
                try:
                    hh = int(c.split(":")[0])
                    if 11 <= hh <= 15:
                        plausible.append(c)
                except Exception:
                    pass
            if len(plausible) >= 2:
                jumuah2_raw = plausible[1]
        if jumuah2_raw:
            jt2 = coerce_time(jumuah2_raw, prayer=Prayer.JUMUAH.value)
            if jt2:
                for dnum in range(1, 32):
                    try:
                        fd = date(year, month, dnum)
                    except ValueError:
                        continue
                    if fd.weekday() == 4:
                        rows.append(
                            ExtractorRow(
                                date=fd,
                                prayer=Prayer.JUMUAH,
                                jamaat_time=jt2,
                                session_number=2,
                                session_label="2nd Jumma",
                                timezone=ctx.timezone,
                                evidence=ctx.evidence(
                                    target_label="timetable",
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    raw_text=jumuah2_raw,
                                    selector="Jumuah footer",
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
