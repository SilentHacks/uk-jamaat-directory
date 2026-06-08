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
           - ``image`` — a screenshot or scan of a printed timetable.
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

        5. If the URL you find is month-specific (e.g. ``/june-2026`` or
           ``/july-timetable``), try to find a pattern or a more stable URL
           first. If there is no stable URL, write the script to construct
           the URL dynamically based on the current date. For example,
           ``f"https://{domain}/{{now.strftime('%B-%Y').lower()}}"`` or
           ``f"https://{domain}/{{now.year}}/{{now.strftime('%m')}}"``.
           You may also use ``relative.add_months`` to handle month
           boundaries.

        6. **JAMAAT times are the goal.** The extractor must find **jamaat**
           (also called **iqamah** or **congregation**) times. These are the
           times when the congregation gathers for prayer. **Adhan** (also
           called **azaan** or **athan**) or **start** times alone are NOT
           sufficient. If the timetable only shows adhan/start times with no
           jamaat/iqamah times, try harder:
           - Look for a separate "jamaat" or "iqamah" column.
           - Check if the page says "jamaat after adhan + X minutes".
           - Look for a downloadable PDF or image that might have jamaat times.
           - If absolutely no jamaat times can be found anywhere on the site,
             set ``status=failed`` with reason ``no jamaat times found``.

        7. Check for **jumuah-only** mosques. If the mosque's timetable only
           shows Jumuah (Friday prayer) and explicitly says "Jumuah only" or
           "No daily prayers", the extractor should:
           - Emit rows with ``prayer="jumuah"`` and ``session_number=1``
             for the Jumuah time.
           - Set ``no_schedule_reason="jumuah_only"`` on the result.
           - Do NOT emit rows for Fajr, Dhuhr, Asr, Maghrib, Isha.
           This is a valid outcome; set ``status=authored``.

        8. If the target is ``html`` or ``rendered_html`` or ``pdf``, write a
           single Python file at the ``Target script path`` above,
           implementing one ``Extractor`` class. The file must satisfy every
           requirement in the "Extractor contract" section below. Validate
           locally with ``python -m uk_jamaat_directory.cli
           validate-repo-extractor --extractor-key {extractor_key}`` before
           finishing.

        9. If the target is ``image``:
           - Write the extractor script anyway. Set the target kind to
             ``image`` and use ``requires_ocr=True``.
           - The script should return ``ExtractorResult(rows=[],
             no_schedule_reason="image target — awaiting OCR")``.
           - The URL is preserved in the ``targets`` so a human can later
             implement OCR and run the extractor again.
           - Set ``status=authored``.

        10. If the target is ``json``, do NOT write a script.
            Just record the discovery with ``status=skipped_review``.

        11. When you are done, write a JSON file to the **exact path**
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

        Required shape (HTML example):

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

        PDF example (set ``requires_pdf=True``):

        ```python
        from uk_jamaat_directory.ingest.extract.helpers import pdf, times, prayers
        from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
            BaseMosqueWebsiteExtractor, ExtractContext, ExtractorResult,
            RefreshPolicy, RunFrequency, SourceMatch, TargetSpec, TargetKind,
        )

        class Extractor(BaseMosqueWebsiteExtractor):
            key = "{extractor_key}"
            version = "YYYY.MM.DD.1"
            source_match = SourceMatch(domains=("{domain}",))
            refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
            targets = (
                TargetSpec(
                    label="timetable",
                    url="<the TARGET_URL you discovered>",
                    kind=TargetKind.PDF,
                    requires_pdf=True,
                ),
            )

            def extract(self, ctx: ExtractContext) -> ExtractorResult:
                artifact = ctx.artifact("timetable")
                text = pdf.extract_text(artifact.body)
                ...
                return ExtractorResult(rows=rows, warnings=warnings)
        ```

        Image example (set ``requires_ocr=True``):

        ```python
        from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
            BaseMosqueWebsiteExtractor, ExtractContext, ExtractorResult,
            RefreshPolicy, RunFrequency, SourceMatch, TargetSpec, TargetKind,
        )

        class Extractor(BaseMosqueWebsiteExtractor):
            key = "{extractor_key}"
            version = "YYYY.MM.DD.1"
            source_match = SourceMatch(domains=("{domain}",))
            refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
            targets = (
                TargetSpec(
                    label="timetable",
                    url="<the TARGET_URL you discovered>",
                    kind=TargetKind.IMAGE,
                    requires_ocr=True,
                ),
            )

            def extract(self, ctx: ExtractContext) -> ExtractorResult:
                return ExtractorResult(
                    rows=[],
                    no_schedule_reason="image target — awaiting OCR",
                )
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
        - For ``image`` targets, set ``requires_ocr=True`` on the
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
