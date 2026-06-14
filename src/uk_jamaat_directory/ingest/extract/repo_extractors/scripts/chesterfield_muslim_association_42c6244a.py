from __future__ import annotations

import re
from datetime import datetime, time

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
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
    key = "chesterfield_muslim_association_42c6244a"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("muslimwelfarechesterfield.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="homepage",
            url="https://muslimwelfarechesterfield.com/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """Extract prayer times from homepage text."""
        artifact = ctx.artifact("homepage")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html_text = artifact.text()
        if len(html_text) < 100:
            return ExtractorResult(rows=[], no_schedule_reason=f"artifact too small: {len(html_text)}")
        
        text = html_helpers.html_to_text(html_text)
        today = datetime.now().date()
        rows = []
        
        # Extract prayer times: Fajr 2:38 am Iqamah 4:00 am
        prayer_patterns = [
            (r"fajr\s+([\d:]+\s*[ap]m)\s+iqamah\s+([\d:]+\s*[ap]m)", Prayer.FAJR),
            (r"zuhr\s+([\d:]+\s*[ap]m)\s+iqamah\s+([\d:]+\s*[ap]m)", Prayer.DHUHR),
            (r"asr\s+([\d:]+\s*[ap]m)\s+iqamah\s+([\d:]+\s*[ap]m)", Prayer.ASR),
            (r"maghrib\s+([\d:]+\s*[ap]m)\s+iqamah\s+([\d:]+\s*[ap]m)", Prayer.MAGHRIB),
            (r"isha\s+([\d:]+\s*[ap]m)\s+iqamah\s+([\d:]+\s*[ap]m)", Prayer.ISHA),
            (r"jumuah\s+([\d:]+\s*[ap]m)\s+iqamah[:\s]+([\d:]+\s*[ap]m)", Prayer.JUMUAH),
        ]
        
        text_lower = text.lower()
        for pattern, prayer in prayer_patterns:
            match = re.search(pattern, text_lower)
            if match:
                iqamah_str = match.group(2).strip()
                jamaat_time = coerce_time(iqamah_str, prayer=prayer.value.lower())
                if jamaat_time:
                    rows.append(ExtractorRow(
                        date=today,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        evidence=ctx.evidence(
                            target_label="homepage",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=iqamah_str,
                        ),
                    ))
        
        if rows:
            return ExtractorResult(rows=rows)
        
        return ExtractorResult(rows=[], no_schedule_reason="no prayer times found")
