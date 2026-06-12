import re
from datetime import date, datetime, timedelta

from uk_jamaat_directory.domain import Prayer
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
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()

        iqamas: dict[str, str] = {}

        # Daily prayer cards: each has prayer-name-en + 3 time-value boxes; 3rd is Iqama (mit)
        for card in re.finditer(
            r'<div[^>]*class="prayer-card"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="prayer-card"|<div[^>]*class="section-title|$)',
            html,
            re.S | re.I,
        ):
            c = card.group(1)
            name_m = re.search(r'class="prayer-name-en">([^<]+)</div>', c, re.I)
            if not name_m:
                continue
            name = name_m.group(1).strip().lower()
            times = re.findall(r'class="time-value">([^<]+)</div>', c)
            if len(times) >= 3:
                iq = times[2].strip()
                if iq:
                    iqamas[name] = iq

        # Special Jumuah card: "Adhan: HH:MM / Iqama: HH:MM"
        m = re.search(
            r'class="special-time"[^>]*>Adhan:\s*[^<]+/\s*Iqama:\s*([^<]+)</div>',
            html,
            re.I,
        )
        if m:
            iqamas["jumaa"] = m.group(1).strip()

        if not iqamas:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no iqama times found in rendered timetable",
                warnings=[
                    ExtractorWarning(
                        code="no_iqamas",
                        message="could not locate Iqama values in prayer cards or special prayers",
                        target_label="timetable",
                    )
                ],
            )

        today = datetime.now().date()
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        prayer_map = {
            "fajr": Prayer.FAJR,
            "dhuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        for key, prayer in prayer_map.items():
            raw = iqamas.get(key)
            if not raw:
                continue
            jamaat = coerce_time(raw, prayer=prayer.value)
            if jamaat is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"today {prayer.value}: {raw!r}",
                        target_label="timetable",
                    )
                )
                continue
            window = PLAUSIBLE_WINDOWS.get(prayer.value)
            if window and not (window[0] <= jamaat <= window[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"today {prayer.value}: {raw!r} outside plausible window",
                        target_label="timetable",
                    )
                )
                continue
            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=f"{key} iqama {raw}",
                        selector="prayer-card iqama",
                    ),
                )
            )

        # One Jumuah row from the listed special time (present on page)
        raw_j = iqamas.get("jumaa") or iqamas.get("jumuah") or iqamas.get("jumu'ah")
        if raw_j:
            jamaat = coerce_time(raw_j, prayer="jumuah")
            if jamaat is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"jumuah: {raw_j!r}",
                        target_label="timetable",
                    )
                )
            else:
                # Emit for the (next) Friday; one listed time -> one row
                days_ahead = (4 - today.weekday()) % 7
                jumuah_date = today if days_ahead == 0 else today + timedelta(days=days_ahead)
                rows.append(
                    ExtractorRow(
                        date=jumuah_date,
                        prayer=Prayer.JUMUAH,
                        jamaat_time=jamaat,
                        session_number=1,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"jumaa iqama {raw_j}",
                            selector="special-card iqama",
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
