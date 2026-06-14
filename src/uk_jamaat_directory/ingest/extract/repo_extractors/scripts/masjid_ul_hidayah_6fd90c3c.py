from uk_jamaat_directory.domain import Prayer
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
    TableTimetableExtractor,
)
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers


class Extractor(TableTimetableExtractor):
    key = "masjid_ul_hidayah_6fd90c3c"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("masjidulhidayah.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://masjidulhidayah.co.uk/",
            kind=TargetKind.RENDERED_HTML,
        ),
    )
    table_keywords = ("date", "fajr")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.DHUHR: "dhuhr",
        Prayer.ASR: "asr",
        Prayer.MAGHRIB: "maghrib",
        Prayer.ISHA: "isha",
    }

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        
        if not tables:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no table found on page",
            )
        
        for table in tables:
            result = self._extract_from_table(ctx, table)
            if result.rows:
                return result
        
        return ExtractorResult(
            rows=[],
            no_schedule_reason="no extractable rows from any table",
        )
