from __future__ import annotations

import re
from datetime import date, datetime, timedelta

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
    key = "king_s_cross_mosque_and_islamic_centre_786961bd"
    version = "2026.06.12.5"
    source_match = SourceMatch(domains=("kingscrossmosque.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    targets = (
        TargetSpec(
            label="timetable",
            url="https://www.kingscrossmosque.org/",
            kind=TargetKind.HTML,
        ),
    )

    def _next_friday(self, base: date) -> date:
        # Friday is weekday 4
        days_ahead = 4 - base.weekday()
        if days_ahead < 0:
            days_ahead += 7
        return base + timedelta(days=days_ahead)

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("timetable")
        if not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")
        # Use plain text extraction (strips tags) so regex works on visible content.
        from uk_jamaat_directory.ingest.extract.helpers.html import html_to_text

        text = html_to_text(artifact.text())
        # The homepage advertises only the two Friday (Jumuah) jamaat times in a static banner.
        # Example visible text (after stripping tags):
        # "Jummah Prayer Times 1st Jama'ah -1:30pm. 2nd Jama'ah - 2:15pm"
        # We must discover the times by parsing; never hard-code values.
        # Collect time-like tokens that appear after a Jummah/Jama mention.
        lower = text.lower()
        marker = lower.find("jummah")
        if marker == -1:
            marker = lower.find("jama")
        window = text[marker:] if marker >= 0 else text

        # Find all HH:MM[am/pm] (with optional space or dot) in the relevant window first,
        # falling back to whole page.
        time_pat = re.compile(r"\b(\d{1,2}[:.]\d{2}\s*(?:am|pm)?)\b", re.IGNORECASE)
        cands = time_pat.findall(window)
        if len(cands) < 2:
            cands = time_pat.findall(text)

        if len(cands) < 2:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_jumuah_text",
                        message="no jumuah jamaat times found in page text",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no jamaat times found",
            )

        t1 = coerce_time(cands[0], prayer="jumuah")
        t2 = coerce_time(cands[1], prayer="jumuah")
        if t1 is None or t2 is None:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="unparseable_jumuah",
                        message=f"could not parse jumuah times {cands[0]!r} / {cands[1]!r}",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no jamaat times found",
            )

        warnings: list[ExtractorWarning] = []
        rows_out: list[ExtractorRow] = []
        # Derive the target Friday from runtime clock (no hard-coded dates/years).
        base = datetime.now().date()
        fri = self._next_friday(base)

        for sess, jt in [(1, t1), (2, t2)]:
            rows_out.append(
                ExtractorRow(
                    date=fri,
                    prayer=Prayer.JUMUAH,
                    jamaat_time=jt,
                    start_time=None,
                    session_number=sess,
                    session_label=f"session {sess}" if sess > 1 else None,
                    timezone=ctx.timezone,
                    evidence=ctx.evidence(
                        target_label="timetable",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=f"jumuah session {sess} {cands[0] if sess == 1 else cands[1]}",
                        selector="homepage jumuah text",
                    ),
                )
            )

        return ExtractorResult(rows=rows_out, warnings=warnings)
