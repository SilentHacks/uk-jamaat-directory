from datetime import datetime

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
    key = "markazi_jamia_masjid_a210e3af"
    version = "2026.06.12.2"
    source_match = SourceMatch(domains=("centralmosquerochdale.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://centralmosquerochdale.com/prayer-times/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        # The JS-rendered board populates these after load:
        # <div class="cmr-ph-iqamah" data-prayer="fajr">04:15</div>
        # etc. Values are the mosque's confirmed jamaat (iqamah) times.
        import re

        jamaat_map: dict[Prayer, str] = {}
        for key, prayer in (
            ("fajr", Prayer.FAJR),
            ("dhuhr", Prayer.DHUHR),
            ("asr", Prayer.ASR),
            ("maghrib", Prayer.MAGHRIB),
            ("isha", Prayer.ISHA),
        ):
            m = re.search(
                rf'data-prayer=["\']{key}["\'][^>]*>([\d:]{{4,5}})<',
                html,
                re.IGNORECASE,
            )
            if m:
                val = m.group(1).strip()
                if val and val not in {"—", "00:00"}:
                    jamaat_map[prayer] = val
        if not jamaat_map:
            return ExtractorResult(
                rows=[], no_schedule_reason="no jamaat times found in rendered board"
            )
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []
        # The board reflects the live/current day on the site.
        row_date = datetime.now().date()
        for prayer, raw in jamaat_map.items():
            jt = coerce_time(raw, prayer=prayer.value)
            if jt is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{row_date} {prayer.value}: {raw!r}",
                        target_label="timetable",
                    )
                )
                continue
            window = PLAUSIBLE_WINDOWS.get(prayer.value)
            if window and not (window[0] <= jt <= window[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"{row_date} {prayer.value}: {raw!r} outside plausible window",
                        target_label="timetable",
                    )
                )
                continue
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
                        raw_text=raw,
                        selector=f"data-prayer={prayer.value}",
                    ),
                )
            )
        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable jamaat rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
