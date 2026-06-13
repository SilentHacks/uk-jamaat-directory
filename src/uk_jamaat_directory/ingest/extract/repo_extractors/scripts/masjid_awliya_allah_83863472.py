from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    TableTimetableExtractor,
)


class Extractor(TableTimetableExtractor):
    key = "masjid_awliya_allah_83863472"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("mapcarta.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://mapcarta.com/W401459734",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    table_keywords = ("date", "prayer", "fajr", "jamaat", "iqamah")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: "jamaat",
        Prayer.DHUHR: "jamaat",
        Prayer.ASR: "jamaat",
        Prayer.MAGHRIB: "jamaat",
        Prayer.ISHA: "jamaat",
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact(self.target_label)
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        
        html = artifact.text()
        
        # Mapcarta is primarily an OSM-derived aggregator listing many places of worship.
        # It does not provide mosque-specific jamaat times.
        lowered = html.lower()
        if ("openstreetmap" in lowered or "osm" in lowered) and "jamaat" not in lowered and "iqamah" not in lowered:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="aggregator listing",
            )
        
        # Search for any table with prayer times
        tables = html_helpers.extract_tables(html)
        
        if not tables:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no timetable table found",
            )
        
        # Look for a table with both prayer names and jamaat times
        timetable = None
        for t in tables:
            joined = " ".join(" ".join(row) for row in t.rows).lower()
            # Must have both prayer keywords and a jamaat/iqamah indicator
            has_prayers = any(p in joined for p in ["fajr", "zuhr", "asr", "maghrib", "isha"])
            has_jamaat = any(j in joined for j in ["jamaat", "iqamah", "congregation"])
            if has_prayers and has_jamaat:
                timetable = t
                break
        
        if timetable is None:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no jamaat times found",
            )
        
        rows_out: list[ExtractorRow] = []
        
        # Use the parent class's extraction logic on the found table
        # For now, if we got here we have a timetable; delegate to parent
        result = self._extract_from_table(ctx, timetable)
        
        if not result.rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason=result.no_schedule_reason or "no extractable rows",
            )
        
        return result
