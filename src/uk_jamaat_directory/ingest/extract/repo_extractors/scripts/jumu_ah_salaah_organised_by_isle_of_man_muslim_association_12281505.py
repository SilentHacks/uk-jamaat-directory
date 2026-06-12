import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time, PLAUSIBLE_WINDOWS
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
    key = "jumu_ah_salaah_organised_by_isle_of_man_muslim_association_12281505"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("iaiom.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://iaiom.com/prayer-time/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        today = datetime.now().date()

        if 'class="prayer-card"' not in html:
            return ExtractorResult(rows=[], no_schedule_reason="prayer widget did not render")

        prayer_map = {
            "Fajr": Prayer.FAJR,
            "Dhuhr": Prayer.DHUHR,
            "Asr": Prayer.ASR,
            "Maghrib": Prayer.MAGHRIB,
            "Isha": Prayer.ISHA,
        }

        cards = re.split(r'<div\s+class="prayer-card"[^>]*>', html, flags=re.IGNORECASE)
        for card_html in cards[1:]:
            name_match = re.search(
                r'<div\s+class="prayer-name-en"[^>]*>\s*(\w+)\s*</div>',
                card_html,
                re.IGNORECASE,
            )
            if not name_match:
                continue
            prayer_name = name_match.group(1)
            prayer_enum = prayer_map.get(prayer_name)
            if prayer_enum is None:
                continue

            iqama_match = re.search(
                r'<div\s+class="time-label"[^>]*>\s*Iqama\s*</div>\s*<div\s+class="time-value"[^>]*>\s*([^<]+)\s*</div>',
                card_html,
                re.IGNORECASE,
            )
            if not iqama_match:
                continue

            time_str = iqama_match.group(1).strip()
            if time_str in ("--:--", "00:00", ""):
                continue

            jamaat = coerce_time(time_str, prayer=prayer_name.lower())
            if jamaat is None:
                continue

            window = PLAUSIBLE_WINDOWS.get(prayer_name.lower())
            if window and not (window[0] <= jamaat <= window[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"{today} {prayer_name}: {time_str!r} outside plausible window",
                        target_label="timetable",
                    )
                )
                continue

            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer_enum,
                    jamaat_time=jamaat,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=f"{prayer_name}: {time_str}",
                        selector="prayer-card",
                    ),
                )
            )

        jumuah_match = re.search(
            r'<div\s+class="special-name-en"[^>]*>\s*Jumaa?\s*</div>.*?'
            r'<div\s+class="special-time"[^>]*>\s*Adhan:\s*([^<]+?)\s*/\s*Iqama:\s*([^<]+?)\s*</div>',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if jumuah_match:
            iqama_str = jumuah_match.group(2).strip()
            jumuah_time = coerce_time(iqama_str, prayer="jumuah")
            if jumuah_time:
                window = PLAUSIBLE_WINDOWS.get("jumuah")
                if not window or (window[0] <= jumuah_time <= window[1]):
                    rows.append(
                        ExtractorRow(
                            date=today,
                            prayer=Prayer.JUMUAH,
                            jamaat_time=jumuah_time,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"Jumuah: {iqama_str}",
                                selector="special-card",
                            ),
                        )
                    )

        if not rows:
            return ExtractorResult(
                rows=[], no_schedule_reason="no extractable prayer times", warnings=warnings
            )

        return ExtractorResult(rows=rows, warnings=warnings)
