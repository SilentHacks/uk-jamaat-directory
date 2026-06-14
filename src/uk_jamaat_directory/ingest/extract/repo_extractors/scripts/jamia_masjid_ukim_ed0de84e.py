import re
from datetime import date

from uk_jamaat_directory.ingest.extract.helpers.html import extract_tables
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
from uk_jamaat_directory.ingest.extract.helpers.times import parse_time_loose
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
    key = "jamia_masjid_ukim_ed0de84e"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("wliconline.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer timetable",
            url="https://wliconline.org/timetable/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        body = ctx.artifact("prayer timetable")
        if not body.body:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="artifact was empty",
            )
        html = body.text()
        tables = extract_tables(html)
        if not tables:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no table present",
            )

        extracted_rows: list[ExtractorRow] = []
        parsed_date = self._extract_date_from_html(html)
        if not parsed_date:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no date found",
            )

        for table in tables:
            rows = list(table.body())
            if len(rows) < 2:
                continue
            for row in rows:
                if not row or len(row) < 3:
                    continue
                prayer = parse_prayer_label(row[0])
                if not prayer:
                    continue
                jammah_time = parse_time_loose(row[2])
                if not jammah_time:
                    continue
                evidence = ctx.evidence(
                    target_label="prayer timetable",
                    extractor_key=self.key,
                    extractor_version=self.version,
                    raw_text=row[2],
                )
                extracted_rows.append(
                    ExtractorRow(
                        date=parsed_date,
                        prayer=prayer,
                        jamaat_time=jammah_time,
                        timezone=ctx.timezone,
                        evidence=evidence,
                    )
                )
            if extracted_rows:
                break

        if not extracted_rows:
            return ExtractorResult(
                rows=[],
                no_schedule_reason="no extractable rows",
            )
        return ExtractorResult(rows=extracted_rows)

    @staticmethod
    def _extract_date_from_html(html: str) -> date | None:
        pattern = r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})"
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            day_str, month_str, year_str = match.groups()
            months = {
                "january": 1,
                "february": 2,
                "march": 3,
                "april": 4,
                "may": 5,
                "june": 6,
                "july": 7,
                "august": 8,
                "september": 9,
                "october": 10,
                "november": 11,
                "december": 12,
            }
            month = months.get(month_str.lower())
            if month:
                try:
                    return date(int(year_str), month, int(day_str))
                except ValueError:
                    pass
        return None
