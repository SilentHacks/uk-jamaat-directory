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
    key = "madina_mosque_e5ac2b61"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("horsham-masjid.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://horsham-masjid.co.uk/",
            kind=TargetKind.HTML,
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

        date_m = re.search(
            r"(\d{1,2}(?:ST|ND|RD|TH)?\s+(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+\d{4})",
            full_text,
            re.IGNORECASE,
        )
        parsed_date = None
        if date_m:
            parsed_date = parse_date_flexible(date_m.group(1), default_year=datetime.now().year)
        if parsed_date is None:
            parsed_date = datetime.now().date()

        jamaat_m = re.search(
            r"JAMA'?AT(.*?)(?:BEGINS|BEGINNINGS|JUMMA|$)", full_text, re.IGNORECASE | re.DOTALL
        )
        jamaat_blob = jamaat_m.group(1) if jamaat_m else full_text
        time_tokens = re.findall(r"\d{1,2}:\d{2}\s*(?:AM|PM)?", jamaat_blob, re.IGNORECASE)
        jamaat_times = [t.strip() for t in time_tokens[:5]]

        prayer_order = [Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA]
        for prayer, raw in zip(prayer_order, jamaat_times):
            jt = coerce_time(raw, prayer=prayer.value)
            if jt is None:
                continue
            win = PLAUSIBLE_WINDOWS.get(prayer.value)
            if win and not (win[0] <= jt <= win[1]):
                continue
            rows.append(
                ExtractorRow(
                    date=parsed_date,
                    prayer=prayer,
                    jamaat_time=jt,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=raw,
                        selector="jamaat banner",
                    ),
                )
            )

        jumuah_m = re.search(r"JUMMA\s*(\d{1,2}:\d{2}\s*(?:AM|PM)?)", full_text, re.IGNORECASE)
        jumuah_raw = jumuah_m.group(1).strip() if jumuah_m else None
        if jumuah_raw and parsed_date.weekday() == 4:
            jt = coerce_time(jumuah_raw, prayer="jumuah")
            if jt:
                win = PLAUSIBLE_WINDOWS.get("jumuah")
                if not win or (win[0] <= jt <= win[1]):
                    rows.append(
                        ExtractorRow(
                            date=parsed_date,
                            prayer=Prayer.JUMUAH,
                            jamaat_time=jt,
                            session_number=1,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=jumuah_raw,
                                selector="jumma banner",
                            ),
                        )
                    )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
