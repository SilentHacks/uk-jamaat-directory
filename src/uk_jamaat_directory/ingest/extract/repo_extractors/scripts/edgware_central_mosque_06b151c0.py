from datetime import datetime
from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorEvidence,
    ExtractorResult,
    ExtractorRow,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
    BaseMosqueWebsiteExtractor,
)
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time


class Extractor(BaseMosqueWebsiteExtractor):
    key = "edgware_central_mosque_06b151c0"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("edgwarecentralmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://edgwarecentralmosque.org/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        
        table = html_helpers.find_table(artifact.text(), header_keywords=("prayer", "jama"))
        if table is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="timetable table not found",
            )
        
        rows = []
        today = datetime.now().date()
        
        for row in table.rows:
            if len(row) < 3:
                continue
            
            prayer_name = row[0].strip().lower()
            prayer = None
            prayer_key = None
            
            if "fajr" in prayer_name:
                prayer = Prayer.FAJR
                prayer_key = "fajr"
            elif "zuhr" in prayer_name or "dhuhr" in prayer_name:
                prayer = Prayer.DHUHR
                prayer_key = "dhuhr"
            elif "asr" in prayer_name:
                prayer = Prayer.ASR
                prayer_key = "asr"
            elif "maghrib" in prayer_name:
                prayer = Prayer.MAGHRIB
                prayer_key = "maghrib"
            elif "isha" in prayer_name:
                prayer = Prayer.ISHA
                prayer_key = "isha"
            
            if prayer is None:
                continue
            
            jamaat_str = row[2].strip()
            jamaat_time = coerce_time(jamaat_str, prayer=prayer_key)
            
            if jamaat_time:
                rows.append(
                    ExtractorRow(
                        date=today,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        evidence=ExtractorEvidence(
                            target_label="timetable",
                            target_url=artifact.target_url,
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=f"{prayer_name}: {jamaat_str}",
                        ),
                    )
                )
        
        return ExtractorResult(rows=rows)

