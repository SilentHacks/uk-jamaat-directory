from __future__ import annotations

import textwrap

from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    SUPPORTED_FREQUENCIES,
    TARGET_KINDS,
)


def build_authoring_prompt(
    *,
    source_id: str,
    mosque_name: str,
    website_url: str,
    extractor_key: str,
    max_pages: int,
) -> str:
    return textwrap.dedent(
        f"""
        You are authoring a repo-owned deterministic extractor for {mosque_name}
        (source_id={source_id}, website={website_url}).

        Output a single Python file at
        `src/uk_jamaat_directory/ingest/extract/repo_extractors/scripts/{extractor_key}.py`.

        Required shape:

        ```python
        from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
            BaseMosqueWebsiteExtractor,
            ExtractContext,
            ExtractorResult,
            ExtractorRow,
            ExtractorWarning,
            RefreshPolicy,
            RunFrequency,
            SourceMatch,
            TargetSpec,
            TargetKind,
        )
        from uk_jamaat_directory.ingest.extract.helpers import html, times, prayers, relative


        class Extractor(BaseMosqueWebsiteExtractor):
            key = "{extractor_key}"
            version = "YYYY.MM.DD.1"

            source_match = SourceMatch(domains=("{website_url.split("://")[-1].split("/")[0]}",))
            refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
            targets = (
                TargetSpec(
                    label="timetable",
                    url="{website_url}",
                    kind=TargetKind.HTML,
                ),
            )

            def extract(self, ctx: ExtractContext) -> ExtractorResult:
                artifact = ctx.artifact("timetable")
                ...
                return ExtractorResult(rows=rows, warnings=warnings)
        ```

        Constraints:

        - The script must implement exactly one `Extractor` class.
        - The script must call the shared helpers; it must NOT import network libraries
          (requests, httpx, urllib, socket, subprocess) or perform file IO outside the
          helpers. Static, capability, output, and candidate validation will run.
        - The script must use `ctx.evidence(...)` for every emitted row.
        - For relative rules such as "Maghrib 5 minutes after adhan", use
          `relative.jamaat_after_start` and store the derivation in evidence.
        - The task is incomplete until `validate-repo-extractor --extractor-key {extractor_key}`
          exits 0 and the synthetic fixture (if any) produces rows that pass
          `validate-candidates`.
        - You may fetch up to {max_pages} pages on the same registrable domain as part of
          investigation; never visit web.archive.org or third-party widgets.

        Available helper modules:

        - `html.parse`, `html.extract_tables`, `html.html_to_text`
        - `times.parse_time_loose`, `times.coerce_time`
        - `prayers.parse_prayer_label`, `prayers.is_jumuah_label`
        - `relative.add_minutes`, `relative.jamaat_after_start`, `relative.parse_offset_minutes`

        Available `RunFrequency` values: {", ".join(SUPPORTED_FREQUENCIES)}.
        Available `TargetKind` values: {", ".join(TARGET_KINDS)}.

        When done, write the file and print a short summary of what you did.
        """
    ).strip()
