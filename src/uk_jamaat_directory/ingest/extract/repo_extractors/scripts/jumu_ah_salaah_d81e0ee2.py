import re
from datetime import datetime, timedelta, date
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


class Extractor(BaseMosqueWebsiteExtractor):
    key = "jumu_ah_salaah_d81e0ee2"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("newmarketmosque.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer-times",
            url="https://newmarketmosque.com/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("prayer-times")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        text = artifact.text()
        warnings = []
        rows = []

        jumu_pattern = r"(?:Juma|Jamat)\s+(?:\d+(?:st|nd|rd|th))?\s*(?:Jamat)?\s*([0-9]{1,2}[:.][0-9]{2})"
        matches = list(re.finditer(jumu_pattern, text, re.IGNORECASE))
        
        if not matches:
            return ExtractorResult(rows=[], no_schedule_reason="no Jumu'ah times found")

        today = date.today()
        days_until_friday = (4 - today.weekday()) % 7
        if days_until_friday == 0:
            friday_date = today
        else:
            friday_date = today + timedelta(days=days_until_friday)

        for session_num, match in enumerate(matches[:2], 1):
            time_str = match.group(1)
            jamaat_time = coerce_time(time_str, prayer="jumuah")
            
            if jamaat_time is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_jumuah_time",
                        message=f"could not parse Jumu'ah time: {time_str!r}",
                        target_label="prayer-times",
                    )
                )
                continue

            rows.append(
                ExtractorRow(
                    date=friday_date,
                    prayer=Prayer.JUMUAH,
                    jamaat_time=jamaat_time,
                    session_number=session_num,
                    session_label=f"Jumu'ah {session_num}",
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="prayer-times",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=time_str,
                        selector=f"jumuah session {session_num}",
                    ),
                )
            )

        return ExtractorResult(rows=rows, warnings=warnings)
