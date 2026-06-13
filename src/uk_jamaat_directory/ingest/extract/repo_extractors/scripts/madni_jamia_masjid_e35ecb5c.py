import re
from datetime import datetime, timedelta

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
    key = "madni_jamia_masjid_e35ecb5c"
    version = "2026.06.13.2"
    source_match = SourceMatch(domains=("icea.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="homepage",
            url="https://www.icea.org.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("homepage")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()
        rows = []

        # Extract date
        date_pattern = r'(\w+\s+\d{1,2},\s+\d{4})'
        date_match = re.search(date_pattern, html)
        if not date_match:
            return ExtractorResult(rows=[], no_schedule_reason="date not found")

        try:
            date_str = date_match.group(1)
            event_date = datetime.strptime(date_str, "%B %d, %Y").date()
        except Exception:
            return ExtractorResult(rows=[], no_schedule_reason="date parsing failed")

        # Extract table rows from HTML
        row_pattern = r'<tr[^>]*>.*?</tr>'
        table_rows = re.findall(row_pattern, html, re.DOTALL)

        if not table_rows:
            return ExtractorResult(rows=[], no_schedule_reason="no table rows found")

        # Find the Jamat row (typically row 4 in the timetable)
        jamat_cells = None
        for row_html in table_rows:
            cells = re.findall(r'<t[dh][^>]*>([^<]*)</t[dh]>', row_html)
            if cells and len(cells) > 0 and cells[0].strip().lower() == 'jamat':
                jamat_cells = [c.strip() for c in cells[1:]]
                break

        if not jamat_cells or len(jamat_cells) < 5:
            return ExtractorResult(rows=[], no_schedule_reason="jamat row not found")

        # Map Jamat row columns to prayers
        # HTML structure has colspan/rowspan: Sunrise spans 2 rows
        # Jamat row after removing first cell: [Fajr, Zuhr, Asr, Maghrib, Isha]
        prayer_col_map = [
            (Prayer.FAJR, 0),
            (Prayer.DHUHR, 1),
            (Prayer.ASR, 2),
            (Prayer.MAGHRIB, 3),
            (Prayer.ISHA, 4),
        ]

        for prayer, col_idx in prayer_col_map:
            if col_idx < len(jamat_cells):
                time_str = jamat_cells[col_idx].strip()
                if time_str and time_str.lower() not in ('', '—', '-'):
                    try:
                        jamaat_time = coerce_time(time_str, prayer=prayer.value.lower())
                        if jamaat_time:
                            evidence = ctx.evidence(
                                target_label="homepage",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"{prayer.value}: {time_str}",
                                selector="prayer_table_jamat_row",
                            )
                            rows.append(
                                ExtractorRow(
                                    date=event_date,
                                    prayer=prayer,
                                    jamaat_time=jamaat_time,
                                    start_time=None,
                                    timezone="Europe/London",
                                    evidence=evidence,
                                )
                            )
                    except Exception:
                        continue

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no jamaat times extracted")

        return ExtractorResult(rows=rows)
