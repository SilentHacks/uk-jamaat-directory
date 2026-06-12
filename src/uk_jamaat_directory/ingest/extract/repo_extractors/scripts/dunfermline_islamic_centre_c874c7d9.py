import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "dunfermline_islamic_centre_c874c7d9"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("dunfermlinecentralmosque.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://dunfermlinecentralmosque.org.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = (
            artifact.body.decode("utf-8", errors="ignore")
            if isinstance(artifact.body, bytes)
            else artifact.body
        )
        rows: list[ExtractorRow] = []

        prayer_map = {
            "fajr": Prayer.FAJR,
            "dhuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }

        # The homepage renders daily jamaat times in <h3>Prayer</h3><h6>HH:MM</h6> blocks
        # (no <table>). Pair nearby h3/h6; skip literal "Sunset" / "--" for Maghrib etc.
        pattern = re.compile(
            r"<h3[^>]*>\s*([^<]+?)\s*</h3>.*?<h6[^>]*>\s*([^<]+?)\s*</h6>",
            re.I | re.S,
        )
        for m in pattern.finditer(html):
            label = m.group(1).strip().lower()
            raw = m.group(2).strip()
            if label not in prayer_map:
                continue
            prayer = prayer_map[label]
            if raw.lower() in ("sunset", "--", "", "sun rise", "sunrise"):
                continue
            jamaat = coerce_time(raw, prayer=prayer.value)
            if jamaat is None:
                continue
            row_date = datetime.now().date()
            rows.append(
                ExtractorRow(
                    date=row_date,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=f"{label} {raw}",
                        selector="cause__content",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no extractable rows")
        return ExtractorResult(rows=rows)
