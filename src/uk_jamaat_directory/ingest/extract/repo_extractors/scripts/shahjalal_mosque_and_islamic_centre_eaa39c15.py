from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import find_table
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
    """Shah Jalal Mosque — homepage "today" widget.

    The widget renders two rows: a ``Begins`` (adhan) row and a ``Jama'ah``
    (congregation) row. The Jama'ah row omits the Sunrise column, so the two
    rows have different widths; we read the Jama'ah row positionally.
    """

    key = "shahjalal_mosque_and_islamic_centre_eaa39c15"
    version = "2026.06.18.1"
    source_match = SourceMatch(domains=("shahjalalmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://shahjalalmosque.org/",
            kind=TargetKind.HTML,
        ),
    )

    # Jama'ah row layout: [label, fajr, zuhr, asr, maghrib, isha]
    _ORDER = (Prayer.FAJR, Prayer.DHUHR, Prayer.ASR, Prayer.MAGHRIB, Prayer.ISHA)

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        table = find_table(artifact.text(), header_keywords=["fajr", "zuhr"])
        if table is None:
            return ExtractorResult(rows=[], no_schedule_reason="timetable table not found")

        jamaah_row = None
        for row in table.body():
            if row and "jama" in row[0].strip().lower():
                jamaah_row = [c.strip() for c in row]
                break
        if jamaah_row is None:
            return ExtractorResult(rows=[], no_schedule_reason="Jama'ah row not found")

        times = jamaah_row[1:]
        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        today = date.today()
        for i, prayer in enumerate(self._ORDER):
            if i >= len(times):
                continue
            jamaat = coerce_time(times[i], prayer=prayer.value)
            if jamaat is None:
                warnings.append(
                    ExtractorWarning(
                        code="unparseable_time",
                        message=f"{prayer.value}: {times[i]!r}",
                        target_label="timetable",
                    )
                )
                continue
            rows.append(
                ExtractorRow(
                    date=today,
                    prayer=prayer,
                    jamaat_time=jamaat,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=f"{prayer.value}: {times[i]}",
                        selector="Jama'ah row",
                    ),
                )
            )
        if not rows:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no jamaat times found"
            )
        return ExtractorResult(rows=rows, warnings=warnings)
