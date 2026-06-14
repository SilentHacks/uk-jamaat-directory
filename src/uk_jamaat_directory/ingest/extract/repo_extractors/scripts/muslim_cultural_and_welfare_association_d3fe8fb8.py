from __future__ import annotations

from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.helpers.dates import parse_date_flexible
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
    key = "muslim_cultural_and_welfare_association_d3fe8fb8"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("mcwas.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.mcwas.org/prayer-times",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        html = artifact.text()
        tables = html_helpers.extract_tables(html)
        if not tables:
            return ExtractorResult(rows=[], no_schedule_reason="no tables found")
        timetable = None
        for t in tables:
            if len(t.rows) >= 5:
                first = t.rows[0]
                if any(":" in (c or "") for c in first):
                    timetable = t
                    break
        if timetable is None:
            timetable = max(tables, key=lambda t: len(t.rows), default=None)
        if timetable is None or not timetable.rows:
            return ExtractorResult(rows=[], no_schedule_reason="no data rows in timetable table")
        year = datetime.now().year
        rows_out: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        target_label = "timetable"
        for rnum, row in enumerate(timetable.rows):
            if not row or not row[0]:
                continue
            date_str = row[0].strip()
            d = parse_date_flexible(date_str, default_year=year)
            if d is None:
                warnings.append(
                    ExtractorWarning(code="bad_date", message=date_str, target_label=target_label)
                )
                continue

            def g(col: int) -> str:
                return (row[col] or "").strip() if col < len(row) else ""

            fj = g(2)
            if fj:
                jt = coerce_time(fj, prayer="fajr")
                if jt:
                    rows_out.append(
                        ExtractorRow(
                            date=d,
                            prayer=Prayer.FAJR,
                            jamaat_time=jt,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label=target_label,
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"{date_str} | fajr_jam={fj}",
                                selector=f"table row {rnum}",
                            ),
                        )
                    )
                else:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{d} fajr: {fj!r}",
                            target_label=target_label,
                        )
                    )
            dj = g(5)
            if dj:
                if "/" in dj:
                    parts = [p.strip() for p in dj.split("/") if p.strip()]
                    for sidx, part in enumerate(parts, start=1):
                        jt = coerce_time(part, prayer="jumuah")
                        if jt:
                            rows_out.append(
                                ExtractorRow(
                                    date=d,
                                    prayer=Prayer.JUMUAH,
                                    jamaat_time=jt,
                                    session_number=sidx,
                                    timezone=ctx.timezone,
                                    evidence=ctx.evidence(
                                        target_label=target_label,
                                        extractor_key=self.key,
                                        extractor_version=self.version,
                                        raw_text=f"{date_str} | jumuah_jam={part}",
                                        selector=f"table row {rnum}",
                                    ),
                                )
                            )
                        else:
                            warnings.append(
                                ExtractorWarning(
                                    code="unparseable_time",
                                    message=f"{d} jumuah: {part!r}",
                                    target_label=target_label,
                                )
                            )
                else:
                    jt = coerce_time(dj, prayer="dhuhr")
                    if jt:
                        rows_out.append(
                            ExtractorRow(
                                date=d,
                                prayer=Prayer.DHUHR,
                                jamaat_time=jt,
                                timezone=ctx.timezone,
                                evidence=ctx.evidence(
                                    target_label=target_label,
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    raw_text=f"{date_str} | zuhr_jam={dj}",
                                    selector=f"table row {rnum}",
                                ),
                            )
                        )
                    else:
                        warnings.append(
                            ExtractorWarning(
                                code="unparseable_time",
                                message=f"{d} zuhr: {dj!r}",
                                target_label=target_label,
                            )
                        )
            aj = g(8)
            if aj:
                jt = coerce_time(aj, prayer="asr")
                if jt:
                    rows_out.append(
                        ExtractorRow(
                            date=d,
                            prayer=Prayer.ASR,
                            jamaat_time=jt,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label=target_label,
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"{date_str} | asr_jam={aj}",
                                selector=f"table row {rnum}",
                            ),
                        )
                    )
                else:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{d} asr: {aj!r}",
                            target_label=target_label,
                        )
                    )
            mgj = g(10)
            if mgj:
                jt = coerce_time(mgj, prayer="maghrib")
                if jt:
                    rows_out.append(
                        ExtractorRow(
                            date=d,
                            prayer=Prayer.MAGHRIB,
                            jamaat_time=jt,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label=target_label,
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"{date_str} | maghrib_jam={mgj}",
                                selector=f"table row {rnum}",
                            ),
                        )
                    )
                else:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{d} maghrib: {mgj!r}",
                            target_label=target_label,
                        )
                    )
            ij = g(12)
            if ij:
                jt = coerce_time(ij, prayer="isha")
                if jt:
                    rows_out.append(
                        ExtractorRow(
                            date=d,
                            prayer=Prayer.ISHA,
                            jamaat_time=jt,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label=target_label,
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"{date_str} | isha_jam={ij}",
                                selector=f"table row {rnum}",
                            ),
                        )
                    )
                else:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{d} isha: {ij!r}",
                            target_label=target_label,
                        )
                    )
        if not rows_out:
            return ExtractorResult(
                rows=[], warnings=warnings, no_schedule_reason="no extractable rows"
            )
        return ExtractorResult(rows=rows_out, warnings=warnings)
