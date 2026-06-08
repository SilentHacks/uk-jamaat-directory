"""Authoring prompt for the overnight extractor orchestrator.

The prompt is the only "policy" the agent has: it tells the agent where to
start, where it is allowed to navigate, what contract to honour, what file
(prayer-timetable extractor script) to write, and what JSON file to write at
the end so the orchestrator can read the result without parsing the agent's
free-form text output.
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
    result_path: str,
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
        Result JSON path: {result_path}

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
            - ``rendered_html`` — the timetable is rendered client-side with
              JavaScript (e.g. Flutter, React, Vue). The runtime uses
              Playwright to fetch the fully-rendered DOM.
            - ``pdf`` — a PDF file. The runtime downloads the PDF and passes
              the raw bytes to the extractor.
            - ``image`` — a screenshot or scan of a printed timetable
              (skip authoring — OCR is not yet implemented).
            - ``json`` — the timetable is served as JSON
              (skip authoring until JSON extractors are supported).

         4. Prefer the **broadest** timetable you can find:
            - A **monthly** or **full-year** timetable is ideal.
            - A **weekly** timetable is acceptable if you cannot find a
              monthly one.
            - A **daily-only** timetable (e.g. "Today's prayer times") is a
              last resort.
            If the first page you find only shows today or this week, keep
            exploring links on the same domain for a monthly or full-year
            version. Use the broadest one you discover before you run out of
            page budget.

         5. If the target is ``html`` or ``rendered_html`` or ``pdf``, write a
            single Python file at the ``Target script path`` above,
            implementing one ``Extractor`` class. The file must satisfy every
            requirement in the "Extractor contract" section below. Validate
            locally with ``python -m uk_jamaat_directory.cli
            validate-repo-extractor --extractor-key {extractor_key}`` before
            finishing.

         6. If the target is ``image`` or ``json``, do NOT write a script.
            Just record the discovery.

         7. When you are done, write a JSON file to the **exact path**
            ``{result_path}``. The orchestrator reads this file after you
            finish — it is the only way the orchestrator knows what you did.

            The JSON file must have this exact structure:

            ```json
            {{
              "status": "authored",
              "target_url": "https://example.com/prayer-times",
              "target_kind": "html",
              "script_path": "{script_path}",
              "reason": "short reason",
              "version": "1.0"
            }}
            ```

            Fields:
            - ``status`` (required): ``authored`` | ``skipped_review`` | ``failed``
            - ``target_url`` (required): the timetable URL you actually visited
            - ``target_kind`` (required): ``html`` | ``rendered_html`` | ``pdf`` |
              ``image`` | ``json``
            - ``script_path`` (required when ``status=authored``): repo-relative path
            - ``reason`` (required when ``status=skipped_review`` or ``failed``): short reason
            - ``version``: always ``"1.0"``

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
        - For ``rendered_html`` targets, set ``requires_javascript=True`` on
          the ``TargetSpec``.
        - For ``pdf`` targets, set ``requires_pdf=True`` on the
          ``TargetSpec``.
        - The script must use ``ctx.evidence(...)`` for every emitted row.
        - For relative rules such as "Maghrib 5 minutes after adhan", use
          ``relative.jamaat_after_start`` and store the derivation in
          evidence.
        - You may visit up to {max_pages} pages on the same registrable
          domain as part of investigation; never visit web.archive.org or
          third-party widgets.

        Available helper modules:

        - ``html.parse``, ``html.extract_tables``, ``html.html_to_text``
        - ``pdf.extract_text``, ``pdf.extract_tables`` (for PDF targets)
        - ``times.parse_time_loose``, ``times.coerce_time``
        - ``prayers.parse_prayer_label``, ``prayers.is_jumuah_label``
        - ``relative.add_minutes``, ``relative.jamaat_after_start``,
          ``relative.parse_offset_minutes``

        # PDF / image / OCR

        OCR and image text extraction are not yet implemented in the runtime.
        If the timetable is a screenshot or scan, set ``status=skipped_review``
        with a ``reason`` like ``image target — ocr not yet implemented``.
        The orchestrator will queue the source for a human.

        # Notes

        - Network access is enabled. Stay on ``{domain}``.
        - The orchestrator reads the JSON file at ``{result_path}`` after you
          finish. If the file is missing or invalid, the task is marked
          ``failed``.
        - Never invent a ``target_url``; it must be a URL you actually visited.
        - Never fabricate rows. If you cannot parse a single row from the
          timetable, set ``status=failed`` with a short reason.
        """
    ).strip()
