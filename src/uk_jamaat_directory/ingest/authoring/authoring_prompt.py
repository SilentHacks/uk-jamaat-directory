"""Authoring prompt for the overnight extractor orchestrator.

The prompt is the only "policy" the agent has: it tells the agent where to
start, where it is allowed to navigate, what contract to honour, what file
to write, and what structured summary to emit at the end.
"""

from __future__ import annotations

import textwrap

from uk_jamaat_directory.domain import AuthoringTargetKind

# Common path fragments the agent can try if it cannot find a link to the
# timetable page. The agent is free to use any of these in addition to
# following links from the homepage.
COMMON_TIMETABLE_PATHS: tuple[str, ...] = (
    "/prayer-times",
    "/prayer-times/",
    "/prayer",
    "/salah",
    "/salat",
    "/namaz",
    "/timetable",
    "/time-table",
    "/schedule",
    "/jumuah",
    "/jumma",
    "/calendar",
    "/mosque-times",
)


def build_authoring_prompt(
    *,
    source_id: str,
    mosque_name: str,
    website_url: str,
    extractor_key: str,
    script_path: str,
    domain: str,
    predicted_kind: AuthoringTargetKind,
    max_pages: int,
) -> str:
    common_paths = "\n".join(f"- {path}" for path in COMMON_TIMETABLE_PATHS)
    kind_hint = (
        f"The pre-flight fetch suggested the timetable may be "
        f"``{predicted_kind.value}``. Confirm this in your exploration; the "
        f"authoring path below depends on the actual target kind."
        if predicted_kind is not AuthoringTargetKind.UNKNOWN
        else "The pre-flight could not classify the target; confirm by visiting the site."
    )
    return textwrap.dedent(
        f"""
        You are authoring a repo-owned deterministic extractor for
        ``{mosque_name}`` (source_id={source_id}).

        Source URL (the only place you start): {website_url}
        Registrable domain (the only place you are allowed to navigate): {domain}
        Target extractor key: {extractor_key}
        Target script path: {script_path}

        {kind_hint}

        # What you must do

        1. Start at the source URL. You may use any tool you need to fetch
           pages, follow links, or read files. You may also try these common
           paths on the same domain if you cannot find a link to the
           timetable from the homepage:

           {common_paths}

        2. Find the prayer-timetable page. It must be on the same registrable
           domain as the source URL. Never visit web.archive.org, third-party
           widgets, social-media profiles, or unrelated domains. If a link
           points off-site, ignore it.

        3. Decide the target kind:
           - ``html`` — a static HTML page with the timetable.
           - ``pdf`` — a PDF file (skip authoring; see "PDF / image / OCR"
             below).
           - ``image`` — a screenshot or scan of a printed timetable
             (skip authoring).
           - ``rendered_html`` — the HTML is empty or only a JavaScript
             container; the timetable is rendered client-side
             (skip authoring).
           - ``json`` — the timetable is served as JSON
             (skip authoring until JSON extractors are supported).

        4. If the target is ``html``, write a single Python file at the
           ``Target script path`` above, implementing one ``Extractor`` class.
           The file must satisfy every requirement in the
           "Extractor contract" section below. Validate locally with
           ``python -m uk_jamaat_directory.cli validate-repo-extractor
           --extractor-key {extractor_key}`` before finishing.

        5. If the target is ``pdf`` / ``image`` / ``rendered_html`` / ``json``,
           do NOT write a script. Just record the discovery.

        6. When you are done, end your reply with a structured summary in
           EXACTLY this format (no extra prose after the block, no code
           fences around it):

           STATUS=authored|skipped_review|failed
           TARGET_URL=<the timetable URL you found, or the source URL if you could not>
           TARGET_KIND=html|pdf|image|rendered_html|json
           SCRIPT_PATH={script_path}     # only when STATUS=authored
           REASON=<short reason>          # only when STATUS=skipped_review or failed

        # Extractor contract

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

            source_match = SourceMatch(domains=("{domain}",))
            refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
            targets = (
                TargetSpec(
                    label="timetable",
                    url="<the TARGET_URL you discovered>",
                    kind=TargetKind.HTML,
                ),
            )

            def extract(self, ctx: ExtractContext) -> ExtractorResult:
                artifact = ctx.artifact("timetable")
                ...
                return ExtractorResult(rows=rows, warnings=warnings)
        ```

        Constraints:

        - The script must implement exactly one ``Extractor`` class.
        - The script must call the shared helpers; it must NOT import
          network libraries (requests, httpx, urllib, socket, subprocess)
          or perform file IO outside the helpers. Static, capability,
          output, and candidate validation will run.
        - The script must use ``ctx.evidence(...)`` for every emitted row.
        - For relative rules such as "Maghrib 5 minutes after adhan", use
          ``relative.jamaat_after_start`` and store the derivation in
          evidence.
        - You may visit up to {max_pages} pages on the same registrable
          domain as part of investigation; never visit web.archive.org or
          third-party widgets.

        Available helper modules:

        - ``html.parse``, ``html.extract_tables``, ``html.html_to_text``
        - ``times.parse_time_loose``, ``times.coerce_time``
        - ``prayers.parse_prayer_label``, ``prayers.is_jumuah_label``
        - ``relative.add_minutes``, ``relative.jamaat_after_start``,
          ``relative.parse_offset_minutes``

        # PDF / image / OCR

        OCR and PDF text extraction are not yet implemented in the runtime.
        If the timetable is a PDF, image, or rendered with JavaScript, set
        ``STATUS=skipped_review`` with a ``REASON`` like ``pdf target — ocr
        not yet implemented`` or ``rendered_html target — playwright not yet
        enabled``. The orchestrator will queue the source for a human.

        # Notes

        - Network access is enabled. Stay on ``{domain}``.
        - The orchestrator captures your stdout, parses the trailing
          ``STATUS=…`` block, validates any file you wrote, and runs
          ``sync_repo_extractors`` so the new extractor is scheduled. If
          validation fails the task is marked ``failed`` and the file you
          wrote is left in place for the operator to inspect.
        - Never invent a TARGET_URL; it must be a URL you actually visited.
        - Never fabricate rows. If you cannot parse a single row from the
          timetable, set ``STATUS=failed`` with a short reason.
        """
    ).strip()
