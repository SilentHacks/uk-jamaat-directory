from datetime import datetime

import re

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
    key = "salisbury_central_masjid_b6a1bbea"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("salisburymuslims.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://salisburymuslims.org.uk/",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()

        m = re.search(r"CSV_RAW\s*=\s*`([^`]+)`", html, re.S)
        if not m:
            return ExtractorResult(rows=[], no_schedule_reason="no CSV prayer data found")
        csv_text = m.group(1).strip()
        lines = [ln.strip() for ln in csv_text.splitlines() if ln.strip()]
        if not lines:
            return ExtractorResult(rows=[], no_schedule_reason="empty CSV data")

        header = [h.strip().lower() for h in lines[0].split(",")]
        idx = {name: i for i, name in enumerate(header)}

        def get(row, name):
            i = idx.get(name.lower())
            if i is None or i >= len(row):
                return ""
            return row[i].strip()

        year = datetime.now().year
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []

        for ln in lines[1:]:
            parts = [p.strip() for p in ln.split(",")]
            if len(parts) < 13:
                continue
            try:
                d = int(parts[0])
                mo = int(parts[1])
                row_date = datetime(year, mo, d).date()
            except Exception:
                continue

            for prayer, adhan_col, iq_col in (
                (Prayer.FAJR, "fajr adhan", "fajr iqamah"),
                (Prayer.DHUHR, "dhuhr adhan", "dhuhr iqamah"),
                (Prayer.ASR, "asr adhan", "asr iqamah"),
                (Prayer.MAGHRIB, "maghrib adhan", "maghrib iqamah"),
                (Prayer.ISHA, "isha adhan", "isha iqamah"),
            ):
                raw_j = get(parts, iq_col)
                if not raw_j:
                    continue
                jt = coerce_time(raw_j, prayer=prayer.value)
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{row_date} {prayer.value}: {raw_j!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                raw_s = get(parts, adhan_col)
                st = coerce_time(raw_s, prayer=prayer.value) if raw_s else None
                rows.append(
                    ExtractorRow(
                        date=row_date,
                        prayer=prayer,
                        jamaat_time=jt,
                        start_time=st,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=ln,
                            selector="csv row",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
