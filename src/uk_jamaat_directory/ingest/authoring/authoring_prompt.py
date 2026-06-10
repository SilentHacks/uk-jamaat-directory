"""Authoring prompts for the overnight extractor orchestrator.

The prompt is the agent's only policy. It is written for a cheap/fast
model: short, imperative, checklist-shaped, with the hard rules first, one
good example, and a mandatory self-test command so the model gets concrete
error feedback instead of guessing.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime

from uk_jamaat_directory.domain import AuthoringTargetKind
from uk_jamaat_directory.ingest.domain_policy import TRUSTED_WIDGET_HOSTS

COMMON_TIMETABLE_PATHS: tuple[str, ...] = (
    "/prayer-times",
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
    today_version = datetime.now(UTC).strftime("%Y.%m.%d.1")
    widget_hosts = ", ".join(sorted(TRUSTED_WIDGET_HOSTS))
    common_paths = ", ".join(COMMON_TIMETABLE_PATHS)
    kind_hint = (
        f"A pre-flight fetch suggests the target kind is `{predicted_kind.value}` — verify it."
        if predicted_kind is not AuthoringTargetKind.UNKNOWN
        else "Pre-flight could not classify the target; check the site."
    )
    return textwrap.dedent(
        f"""
        Write a deterministic prayer-timetable extractor for the mosque
        **{mosque_name}** (source_id={source_id}).

        - Start URL: {website_url}
        - Allowed domain: {domain} (you may visit up to {max_pages} pages on it)
        - Also allowed as extractor targets: timetable widgets the mosque embeds
          from {widget_hosts}
        - Script path to write: {script_path}
        - Result JSON path to write when done: {result_path}
        - Extractor key: {extractor_key}   Extractor version: {today_version}

        {kind_hint}

        # STOP conditions — check these FIRST

        - If the site is a mosque **directory/aggregator** (lists many mosques,
          shows calculated prayer times): write the result JSON with
          `status=failed`, `reason=aggregator listing`. Do not write a script.
        - **JAMAAT (iqamah/congregation) times are the goal.** Adhan/start
          times alone are NOT enough. Look for a jamaat/iqamah column, an
          "jamaat = adhan + N minutes" rule, or a PDF/image timetable. If the
          whole site only has adhan/start times: `status=failed`,
          `reason=no jamaat times found`.
        - Never visit other domains (no web.archive.org, no social media).

        # Hard rules for the script

        - NEVER hardcode clock times, dates, or years. Use
          `datetime.now().year` / the `dates` helpers for the current year.
        - NEVER invent rows. Only emit times that appear in the source. If the
          page lists one Jumuah, emit one Jumuah row.
        - Only import: `datetime`, `re`, and
          `uk_jamaat_directory.ingest.extract.helpers.*`,
          `uk_jamaat_directory.ingest.extract.repo_extractors.contract`,
          `uk_jamaat_directory.ingest.extract.repo_extractors.declarative`,
          `uk_jamaat_directory.domain`. No network/file libraries — the
          runtime fetches the target URLs and passes them in as artifacts.

        # Steps

        1. Find the timetable page on {domain}. If the homepage has no link,
           try these paths: {common_paths}
        2. Prefer the broadest timetable: monthly/yearly > weekly > today-only.
           If the URL is month-specific (e.g. /june-2026), build it dynamically
           from the current date in `targets` (compute in `__init__`).
        3. Decide the kind: `html` (static), `rendered_html` (JS-rendered; set
           `requires_javascript=True`), `pdf` (set `requires_pdf=True`),
           `image` (set `requires_ocr=True`), or `json` (do NOT author —
           `status=skipped_review`).
        4. Write the script. **Default to the declarative base classes** —
           only subclass `BaseMosqueWebsiteExtractor` directly if the page
           cannot be expressed as a table. Example of a complete, good script:

        ```python
        from uk_jamaat_directory.domain import Prayer
        from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
            RefreshPolicy, RunFrequency, SourceMatch, TargetKind, TargetSpec,
        )
        from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
            TableTimetableExtractor,
        )


        class Extractor(TableTimetableExtractor):
            key = "{extractor_key}"
            version = "{today_version}"
            source_match = SourceMatch(domains=("{domain}",))
            refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
            targets = (
                TargetSpec(
                    label="timetable",
                    url="<the timetable URL you found>",
                    kind=TargetKind.HTML,
                ),
            )
            table_keywords = ("date", "fajr")     # all must appear in the header
            date_column = "date"                  # header keyword or column index
            # Use an index (e.g. date_column = 0) when the date column has a
            # blank header. Bare day numbers ("1", "21st") are handled — the
            # base fills in the current month/year.
            prayer_columns = {{                    # JAMAAT columns only
                Prayer.FAJR: "fajr",
                Prayer.DHUHR: "zuhr",
                Prayer.ASR: "asr",
                Prayer.MAGHRIB: "maghrib",
                Prayer.ISHA: "isha",
            }}
        ```

           For PDFs use `PdfTableTimetableExtractor` (same config). For images
           use `StubbedOcrExtractor` (no config beyond targets — OCR comes
           later; that counts as `status=authored`). The bases handle date
           parsing, am/pm inference, evidence, and warnings. Override the
           `clean_cell` / `accept_row` hooks for site quirks. Other helpers:
           `helpers.times.coerce_time(value, prayer=...)`,
           `helpers.dates.parse_date_flexible/add_months/dates_for_month`,
           `helpers.rows.carry_forward`, `helpers.html.find_table`,
           `helpers.prayers.parse_prayer_label`,
           `helpers.relative.jamaat_after_start` (for "jamaat = adhan + N min").

        5. **Self-test (mandatory).** Run:

           `python -m uk_jamaat_directory.cli smoke-test-repo-extractor --extractor-key {extractor_key} --source-url {website_url}`

           It fetches your target URLs, runs your script in the sandbox, and
           checks the output is a plausible jamaat timetable. If it exits
           non-zero, fix the script and re-run. Do NOT report
           `status=authored` until it exits 0.

        6. Write the result JSON to exactly `{result_path}`:

        ```json
        {{
          "status": "authored | skipped_review | failed",
          "target_url": "<the timetable URL you actually visited>",
          "target_kind": "html | rendered_html | pdf | image | json",
          "script_path": "{script_path}",
          "reason": "<required for skipped_review/failed>",
          "version": "1.0"
        }}
        ```

        The orchestrator only reads that file. If it is missing or invalid,
        the task is marked failed.
        """
    ).strip()


def build_repair_prompt(
    *,
    mosque_name: str,
    extractor_key: str,
    script_path: str,
    result_path: str,
    source_url: str,
    issues: list[str],
    attempt: int,
) -> str:
    issue_lines = "\n".join(f"- {issue}" for issue in issues)
    return textwrap.dedent(
        f"""
        Your extractor script for **{mosque_name}** (key={extractor_key}) at
        `{script_path}` failed validation (repair attempt {attempt}):

        {issue_lines}

        Fix the script in place, then re-run the self-test:

        `python -m uk_jamaat_directory.cli smoke-test-repo-extractor --extractor-key {extractor_key} --source-url {source_url}`

        Repeat until it exits 0. Remember: never hardcode times/dates/years,
        never invent rows, jamaat (not adhan) times are required, and only the
        allowed helper imports may be used.

        When it passes, rewrite the result JSON at `{result_path}` with
        `status=authored`, the real `target_url` and `target_kind`,
        `script_path={script_path}`, and `version="1.0"`.
        If the issues cannot be fixed (e.g. the site truly has no jamaat
        times), write `status=failed` with a short `reason`.
        """
    ).strip()
