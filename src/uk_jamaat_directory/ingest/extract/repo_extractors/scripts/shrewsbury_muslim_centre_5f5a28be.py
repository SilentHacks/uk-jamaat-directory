from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.prayers import parse_prayer_label
from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS, coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractorResult,
    ExtractorRow,
    ExtractorWarning,
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
    key = "shrewsbury_muslim_centre_5f5a28be"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("shrewsburymuslimcentre.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://shrewsburymuslimcentre.org/prayer-times/",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("date", "prayer", "starts", "jamat")
    date_column = "date"

    def extract(self, ctx):
        artifact = ctx.artifact(self.target_label)
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        target_table = None
        for t in tables:
            h = [c.lower() for c in t.header]
            if "date" in " ".join(h) and ("jamat" in " ".join(h) or "jamaat" in " ".join(h)):
                target_table = t
                break
        if target_table is None:
            for t in tables:
                joined = " ".join(" ".join(r) for r in t.rows).lower()
                if "fajr" in joined and ("jamat" in joined or "starts" in joined):
                    target_table = t
                    break
        if target_table is None:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        current_date_text = ""
        year = self.current_year(ctx)
        month = self.current_month(ctx)

        for r in target_table.body():
            if not r:
                continue
            if len(r) >= 4:
                date_text = r[0]
                prayer_text = r[1]
                start_text = r[2]
                jamaat_text = r[3]
            elif len(r) == 3:
                date_text = ""
                prayer_text = r[0]
                start_text = r[1]
                jamaat_text = r[2]
            else:
                continue

            if date_text and date_text.strip():
                current_date_text = date_text.strip()
            if not current_date_text:
                continue
            if "date" in current_date_text.lower():
                continue

            row_date = self.parse_date_cell(current_date_text, year=year, month=month)
            if row_date is None:
                continue

            prayer = parse_prayer_label(prayer_text)
            if prayer is None:
                continue

            jamaat = coerce_time(jamaat_text, prayer=prayer.value)
            if jamaat is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{row_date} {prayer.value}: {jamaat_text!r}",
                        target_label=self.target_label,
                    )
                )
                continue

            window = PLAUSIBLE_WINDOWS.get(prayer.value)
            if window and not (window[0] <= jamaat <= window[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"{row_date} {prayer.value}: {jamaat_text!r} outside plausible window",
                        target_label=self.target_label,
                    )
                )
                continue

            start = coerce_time(start_text, prayer=prayer.value) if start_text else None

            rows.append(
                ExtractorRow(
                    date=row_date,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    start_time=start,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label=self.target_label,
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=" | ".join(
                            [current_date_text, prayer_text, start_text or "", jamaat_text or ""]
                        ),
                        selector="prayer times table row",
                    ),
                )
            )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )

        order = {
            Prayer.FAJR: 0,
            Prayer.DHUHR: 1,
            Prayer.ASR: 2,
            Prayer.MAGHRIB: 3,
            Prayer.ISHA: 4,
            Prayer.JUMUAH: 5,
        }
        rows.sort(key=lambda r: (r.date, order.get(r.prayer, 999), r.session_number))
        return ExtractorResult(rows=rows, warnings=warnings)
