from __future__ import annotations

from datetime import datetime

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
    key = "central_park_community_centre_856f023d"
    version = "2026.06.12.1"
    source_match = SourceMatch(domains=("centralparkcommunitycentre.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)

    targets = (
        TargetSpec(
            label="timetable",
            url="https://centralparkcommunitycentre.com/",
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

        warnings: list[ExtractorWarning] = []
        rows: list[ExtractorRow] = []
        today = datetime.now().date()

        prayer_keys = [
            ("fajr", Prayer.FAJR),
            ("zuhr", Prayer.DHUHR),
            ("dhuhr", Prayer.DHUHR),
            ("asr", Prayer.ASR),
            ("'asr", Prayer.ASR),
            ("maghrib", Prayer.MAGHRIB),
            ("isha", Prayer.ISHA),
            ("'isha", Prayer.ISHA),
            ("ishā", Prayer.ISHA),
        ]

        for table in tables:
            # Build list of all rows (header + body) for scanning
            all_rows: list[list[str]] = []
            if table.header:
                all_rows.append([(c or "").strip() for c in table.header])
            for r in table.rows or []:
                all_rows.append([(c or "").strip() for c in r])

            if not all_rows:
                continue

            # Locate prayer column indices from any row that mentions prayer names
            prayer_col: dict[Prayer, int] = {}
            for r in all_rows:
                lower = [c.lower() for c in r]
                for key, pr in prayer_keys:
                    for col, cell in enumerate(lower):
                        if key in cell:
                            prayer_col[pr] = col
                            break
                if prayer_col:
                    break

            if not prayer_col:
                continue

            # Find the Jama'ah row (the one with jamaat/iqamah times for today)
            jama_row: list[str] | None = None
            for r in all_rows:
                joined_lower = " ".join(c.lower() for c in r)
                if "jama" in joined_lower or "iqama" in joined_lower or "iqamah" in joined_lower:
                    jama_row = r
                    break

            if jama_row is None:
                continue

            for prayer, col in prayer_col.items():
                if col >= len(jama_row):
                    continue
                raw = jama_row[col]
                if not raw or ":" not in raw:
                    continue
                jt = coerce_time(raw, prayer=prayer.value)
                if jt is None:
                    warnings.append(
                        ExtractorWarning(
                            code="unparseable_time",
                            message=f"{today} {prayer.value}: {raw!r}",
                            target_label="timetable",
                        )
                    )
                    continue
                win = PLAUSIBLE_WINDOWS.get(prayer.value)
                if win and not (win[0] <= jt <= win[1]):
                    warnings.append(
                        ExtractorWarning(
                            code="implausible_time",
                            message=f"{today} {prayer.value}: {raw!r} outside plausible window",
                            target_label="timetable",
                        )
                    )
                    continue
                rows.append(
                    ExtractorRow(
                        date=today,
                        prayer=prayer,
                        jamaat_time=jt,
                        timezone=ctx.timezone,
                        evidence=ctx.evidence(
                            target_label="timetable",
                            extractor_key=self.key,
                            extractor_version=self.version,
                            raw_text=" | ".join(jama_row),
                            selector="jama'ah row",
                        ),
                    )
                )

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no jamaat rows extracted",
            )

        # Dedup: the page renders the same daily grid in header + body
        seen: set[tuple] = set()
        deduped: list[ExtractorRow] = []
        for r in rows:
            key = (r.date, r.prayer, r.session_number)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)
        return ExtractorResult(rows=deduped, warnings=warnings)
