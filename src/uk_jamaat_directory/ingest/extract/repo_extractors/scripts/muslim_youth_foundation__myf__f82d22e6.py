"""
Extractor for Muslim Youth Foundation (MYF) jamaat times.
Parses fixed jamaat times and relative offsets from the homepage.
"""

import re
from datetime import date

from uk_jamaat_directory.domain import Prayer
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
    """
    Extract jamaat times from MYF homepage.

    MYF publishes:
    - Fixed jamaat times: Fajr 03:30am, Dhuhr 1:30pm
    - Relative times: Asr & Maghrib 7 mins after adhan
    - Combined Isha with Maghrib
    - Jumuah prayers: 1st 12:00pm, 2nd 12:30pm, 3rd 1:15pm
    """

    key = "muslim_youth_foundation__myf__f82d22e6"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("myf.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="homepage",
            url="https://myf.org.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("homepage")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        rows: list[ExtractorRow] = []

        # MYF publishes fixed daily jamaat times year-round
        today = date.today()

        # Fajr: 03:30am daily
        fajr_found = re.search(r"(?:Fajr|fajr).*?03:30\s*(?:am|AM)", html)
        if fajr_found:
            evidence = ctx.evidence(
                target_label="homepage",
                extractor_key=self.key,
                extractor_version=self.version,
                raw_text="Fajr 03:30am",
            )
            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=Prayer.FAJR,
                    jamaat_time="03:30",
                    timezone=ctx.timezone,
                    evidence=evidence,
                )
            )

        # Dhuhr: 1:30pm (13:30) daily
        dhuhr_found = re.search(r"(?:Dhur|dhuhr).*?1:30\s*(?:pm|PM)", html)
        if dhuhr_found:
            evidence = ctx.evidence(
                target_label="homepage",
                extractor_key=self.key,
                extractor_version=self.version,
                raw_text="Dhuhr 1:30pm",
            )
            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=Prayer.DHUHR,
                    jamaat_time="13:30",
                    timezone=ctx.timezone,
                    evidence=evidence,
                )
            )

        # Asr & Maghrib: 7 mins after adhan (relative - cannot emit without adhan times)
        # These are relative offsets that require external adhan data
        # Skip them since the source doesn't provide absolute times

        # Jumuah: 1st 12:00pm, 2nd 12:30pm, 3rd 1:15pm
        jumuah_patterns = [
            (r"1st.*?12:00\s*(?:pm|PM)", "12:00", 1, "1st Jumuah"),
            (r"2nd.*?12:30\s*(?:pm|PM)", "12:30", 2, "2nd Jumuah"),
            (r"3rd.*?1:15\s*(?:pm|PM)", "13:15", 3, "3rd Jumuah"),
        ]

        for pattern, time_hhmm, slot, label in jumuah_patterns:
            if re.search(pattern, html, re.IGNORECASE):
                evidence = ctx.evidence(
                    target_label="homepage",
                    extractor_key=self.key,
                    extractor_version=self.version,
                    raw_text=label,
                )
                rows.append(
                    ExtractorRow(
                        date=today,
                        prayer=Prayer.JUMUAH,
                        jamaat_time=time_hhmm,
                        session_number=slot,
                        timezone=ctx.timezone,
                        evidence=evidence,
                    )
                )

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no jamaat times found")

        return ExtractorResult(rows=rows)
