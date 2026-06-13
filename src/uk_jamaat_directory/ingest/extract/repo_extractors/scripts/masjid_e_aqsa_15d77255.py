from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorResult,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    BaseMosqueWebsiteExtractor,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "masjid_e_aqsa_15d77255"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("masjid-e-aqsa.net",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjid-e-aqsa.net/",
            kind=TargetKind.HTML,
        ),
    )
    target_label = "timetable"

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact.body or len(artifact.body.strip()) == 0:
            return ExtractorResult(rows=[], no_schedule_reason="image target — awaiting OCR")
        
        html_text = artifact.text()
        
        # Look for any table or timetable structure
        tables = html_helpers.extract_tables(html_text)
        if not tables:
            return ExtractorResult(rows=[], no_schedule_reason="image target — awaiting OCR")
        
        # If we got here but no rows, the site structure is not extractable
        return ExtractorResult(rows=[], no_schedule_reason="image target — awaiting OCR")
