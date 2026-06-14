from __future__ import annotations

import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
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
    key = "woodfarm_education_centre_994189a2"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("woodfarmeducationcentre.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://woodfarmeducationcentre.org.uk/prayer-time-table/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        # The page uses the daily-prayer-time-for-mosques WP plugin.
        # It renders a compact horizontal table for "today":
        #   header row with prayer names (Fajr, Sunrise, Zuhr, Asr, Maghrib, Isha)
        #   "Begins" row (adhan/start)
        #   "Jamaat" row (iqamah/congregation) with values in cells (some class=jamah)
        # We parse the explicit Jamaat row values aligned to the prayer headers.
        # This is a today-only widget (date shown in title cell); we emit for datetime.now().date().

        # Find the dpt timetable (horizontal layout)
        tbl_match = re.search(
            r"<table[^>]*class=[^>]*dptTimetable[^>]*>.*?</table>",
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if not tbl_match:
            tbl_match = re.search(
                r"<table[^>]*class=[^>]*customStyles[^>]*>.*?</table>",
                html,
                re.DOTALL | re.IGNORECASE,
            )
        if not tbl_match:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")

        tbl_html = tbl_match.group(0)

        # Locate the prayer header row and the Jamaat row by scanning table rows.
        # The header row's first non-empty cell text is "Prayer".
        # The Jamaat row's first non-empty cell text is "Jamaat".
        # Avoid the title row which may contain the word "Jamaat" inside countdown text.
        rows_html = re.findall(r"<tr[^>]*>.*?</tr>", tbl_html, re.DOTALL | re.IGNORECASE)
        header_html = ""
        jamaat_html = ""
        for r in rows_html:
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.DOTALL | re.IGNORECASE)
            texts = [re.sub(r"<[^>]+>", " ", c).strip() for c in cells if re.sub(r"<[^>]+>", " ", c).strip()]
            if not texts:
                continue
            first = texts[0].lower()
            if first == "prayer" and not header_html:
                header_html = r
            if first == "jamaat" and not jamaat_html:
                jamaat_html = r
        if not header_html or not jamaat_html:
            return ExtractorResult(rows=[], no_schedule_reason="no jamaat times found")

        # Extract ordered prayer labels from header (skip the leading "Prayer" label cell)
        prayer_labels: list[str] = []
        for m in re.finditer(r"<t[hd][^>]*>(.*?)</t[hd]>", header_html, re.DOTALL | re.IGNORECASE):
            txt = re.sub(r"<[^>]+>", " ", m.group(1)).strip()
            if txt:
                prayer_labels.append(txt)
        # First is "Prayer", then Fajr, Sunrise, Zuhr, Asr, Maghrib, Isha (Sunrise has no jamaat)
        if prayer_labels and prayer_labels[0].lower() == "prayer":
            prayer_labels = prayer_labels[1:]

        # Extract cell texts from the Jamaat row (td/th values after the "Jamaat" label)
        jamaat_cells: list[str] = []
        for m in re.finditer(r"<t[hd][^>]*>(.*?)</t[hd]>", jamaat_html, re.DOTALL | re.IGNORECASE):
            txt = re.sub(r"<[^>]+>", " ", m.group(1)).strip()
            if txt:
                jamaat_cells.append(txt)

        # Align: jamaat row typically starts with "Jamaat" label then values for Fajr, Zuhr, Asr, Maghrib, Isha
        # (Sunrise omitted). Map by known order skipping Sunrise.
        # Build mapping from label to jamaat raw
        jam_map: dict[str, str] = {}
        # prayer_labels after strip: e.g. ['Fajr','Sunrise','Zuhr','Asr','Maghrib','Isha']
        # jamaat_cells after strip: e.g. ['Jamaat','1:45 am','2:00 pm','7:30 pm','10:10 pm','11:10 pm']
        if jamaat_cells and jamaat_cells[0].lower() == "jamaat":
            jamaat_cells = jamaat_cells[1:]
        # Map sequentially, skipping Sunrise column if present in labels
        j_idx = 0
        for lbl in prayer_labels:
            llow = lbl.lower()
            if "sunrise" in llow or "sun rise" in llow:
                continue
            if j_idx < len(jamaat_cells):
                jam_map[lbl] = jamaat_cells[j_idx]
                j_idx += 1

        row_date = datetime.now().date()

        for lbl, raw_j in jam_map.items():
            prayer = parse_prayer_label(lbl)
            if prayer is None or prayer == Prayer.JUMUAH:
                continue
            jamaat = coerce_time(raw_j, prayer=prayer.value)
            if jamaat is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{row_date} {prayer.value}: {raw_j!r}",
                        target_label="timetable",
                    )
                )
                continue
            window = PLAUSIBLE_WINDOWS.get(prayer.value)
            if window and not (window[0] <= jamaat <= window[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"{row_date} {prayer.value}: {raw_j!r} outside plausible window",
                        target_label="timetable",
                    )
                )
                continue
            rows.append(
                ExtractorRow(
                    date=row_date,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    start_time=None,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=f"{lbl} | {raw_j}",
                        selector="dpt horizontal jamaat row",
                    ),
                )
            )

        # Also surface Jumuah from the seasonal advisory text if times are present for today
        # (text like "(Winter) Main Jumuah: 1PM. Schools Jumuah: 12:30pm.")
        # We only emit if explicit clock times are found; do not invent.
        jumuah_texts = re.findall(
            r"Jumuah[^:]*:\s*([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)",
            html,
            re.IGNORECASE,
        )
        for sidx, raw in enumerate(jumuah_texts, 1):
            jt = coerce_time(raw, prayer=Prayer.JUMUAH.value)
            if jt is None:
                continue
            win = PLAUSIBLE_WINDOWS.get(Prayer.JUMUAH.value)
            if win and not (win[0] <= jt <= win[1]):
                continue
            rows.append(
                ExtractorRow(
                    date=row_date,
                    prayer=Prayer.JUMUAH,
                    jamaat_time=jt,
                    start_time=None,
                    session_number=sidx,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=raw,
                        selector="jumuah advisory text",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no extractable rows")

        order = {
            Prayer.FAJR: 0,
            Prayer.DHUHR: 1,
            Prayer.ASR: 2,
            Prayer.MAGHRIB: 3,
            Prayer.ISHA: 4,
            Prayer.JUMUAH: 5,
        }
        rows.sort(key=lambda r: (r.date, order.get(r.prayer, 999), r.session_number))
        return ExtractorResult(rows=rows, warnings=warnings)
