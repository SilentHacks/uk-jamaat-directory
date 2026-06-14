from datetime import datetime
import re

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.times import PLAUSIBLE_WINDOWS, coerce_time
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
    key = "worthing_masjid_a08764e7"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("worthingmasjid.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://masjidal.com/widget/simple?masjid_id=XAlRl6Kb",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        if not tables:
            return ExtractorResult(rows=[], no_schedule_reason="no tables in rendered widget")
        prayer_label_map = {
            "fajr": Prayer.FAJR,
            "dhuhr": Prayer.DHUHR,
            "zuhr": Prayer.DHUHR,
            "asr": Prayer.ASR,
            "maghrib": Prayer.MAGHRIB,
            "isha": Prayer.ISHA,
        }
        jumuah_times: list[str] = []
        regular: dict[Prayer, str] = {}
        for table in tables:
            for row in table.rows:
                if not row:
                    continue
                first = row[0].strip().lower()
                if first in prayer_label_map:
                    pr = prayer_label_map[first]
                    candidate_cells = row[1:]
                    raw = ""
                    for c in reversed(candidate_cells):
                        if re.search(r"[\d:]{3,5}", c):
                            raw = c.strip()
                            break
                    if raw:
                        regular[pr] = raw
                elif "jumu" in first or "jumma" in first or "jum'ah" in first:
                    for c in row[1:]:
                        for tm in re.findall(r"[\d:]{3,5}", c):
                            if tm not in jumuah_times:
                                jumuah_times.append(tm)
        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []
        today = datetime.now().date()
        for pr, raw in regular.items():
            jt = coerce_time(raw, prayer=pr.value)
            if jt is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{today} {pr.value}: {raw!r}",
                        target_label="timetable",
                    )
                )
                continue
            w = PLAUSIBLE_WINDOWS.get(pr.value)
            if w and not (w[0] <= jt <= w[1]):
                warnings.append(
                    ExtractorWarning(
                        code="implausible_time",
                        message=f"{today} {pr.value}: {raw!r} outside plausible window",
                        target_label="timetable",
                    )
                )
                continue
            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=pr,
                    jamaat_time=jt,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=raw,
                        selector="widget iqama cell",
                    ),
                )
            )
        for i, raw in enumerate(jumuah_times, 1):
            jt = coerce_time(raw, prayer="jumuah")
            if jt is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{today} jumuah#{i}: {raw!r}",
                        target_label="timetable",
                    )
                )
                continue
            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=Prayer.JUMUAH,
                    jamaat_time=jt,
                    session_number=i,
                    session_label=f"session {i}" if len(jumuah_times) > 1 else None,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=raw,
                        selector=f"widget jumuah iqama {i}",
                    ),
                )
            )
        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no jamaat times found in rendered widget",
            )
        return ExtractorResult(rows=rows, warnings=warnings)
