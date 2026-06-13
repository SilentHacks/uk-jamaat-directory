from datetime import datetime
from uk_jamaat_directory.domain import Prayer
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

PRAYER_CLASSES = {
    Prayer.FAJR: "scFajr",
    Prayer.DHUHR: "scZuhr",
    Prayer.ASR: "scAsr",
    Prayer.MAGHRIB: "scMaghrib",
    Prayer.ISHA: "scIsha",
    Prayer.JUMUAH: "scJumuah",
}


class Extractor(BaseMosqueWebsiteExtractor):
    key = "the_islambradford_centre_9adfbf58"
    version = "2026.06.13.2"
    source_match = SourceMatch(domains=("islambradford.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="daily_timetable",
            url="https://islambradford.com/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("daily_timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()

        warnings: list[ExtractorWarning] = []
        parsed_rows: list[ExtractorRow] = []
        today = datetime.now().date()

        for prayer, css_class in PRAYER_CLASSES.items():
            start = html.find(f"span class='{css_class}")
            if start == -1:
                start = html.find(f'span class="{css_class}')
            if start == -1:
                continue

            section = html[start : start + 500]
            time_start = section.find("<span class='dpt_jamah")
            if time_start == -1:
                time_start = section.find('<span class="dpt_jamah')
            if time_start == -1:
                continue

            time_start = section.find(">", time_start) + 1
            time_end = section.find("</span>", time_start)
            if time_end == -1:
                continue

            raw_time = section[time_start:time_end].strip()
            if raw_time and raw_time != "N/A":
                jamaat = coerce_time(raw_time, prayer=prayer.value)
                if jamaat is not None:
                    parsed_rows.append(
                        ExtractorRow(
                            date=today,
                            prayer=prayer,
                            jamaat_time=jamaat,
                            start_time=None,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="daily_timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"{prayer.value}: {raw_time}",
                                selector=f"span.{css_class}",
                            ),
                        )
                    )
                else:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{prayer.value}: {raw_time!r}",
                            target_label="daily_timetable",
                        )
                    )

        if not parsed_rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no extractable times found",
            )

        return ExtractorResult(rows=parsed_rows, warnings=warnings)
