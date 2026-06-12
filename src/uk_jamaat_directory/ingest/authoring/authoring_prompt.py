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
        **{mosque_name}** (source_id={source_id}). Work alone: do NOT spawn
        subagents or use any task/agent-delegation tool — do every step
        yourself.

        - Start URL: {website_url}
        - Allowed domain: {domain} (visit up to {max_pages} pages on it; never
          leave it — no web.archive.org, no social media)
        - Also allowed as targets: timetable widgets embedded from {widget_hosts}
        - Write the script to: {script_path}
        - Write the result JSON to: {result_path}
        - Extractor key: {extractor_key}   version: {today_version}

        {kind_hint}

        # Goal: JAMAAT (iqamah/congregation) times

        Adhan/start times alone are NOT the goal. You need a jamaat/iqamah
        column, a "jamaat = adhan + N minutes" rule, or a PDF/image timetable.
        Stop early and write the result JSON (no script) if:
        - the site is a directory/**aggregator** (many mosques, calculated
          times): `status=failed`, `reason=aggregator listing`.
        - the whole site has only adhan/start times: `status=failed`,
          `reason=no jamaat times found`.

        # Steps

        1. Find the broadest timetable on {domain} (monthly/yearly > weekly >
           today-only). If the homepage has no link, try: {common_paths}
        2. Pick the base class for what you found and write the script:
           - HTML table -> `TableTimetableExtractor` (`kind=TargetKind.HTML`)
           - JS-rendered -> same, `kind=TargetKind.RENDERED_HTML`,
             `requires_javascript=True`
           - PDF -> `StubbedPdfExtractor`, `kind=TargetKind.PDF`,
             `requires_pdf=True`. Do NOT parse the PDF — the stub just records
             the target; that still counts as `status=authored`.
           - image -> `StubbedOcrExtractor`, `kind=TargetKind.IMAGE`,
             `requires_ocr=True` (stubbed, also `status=authored`).
           - JSON feed -> do NOT author; `status=skipped_review`.
           If a month-specific URL (e.g. /june-2026), build it from the current
           date in `__init__`.

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
            # Use an index (e.g. date_column = 0) when the date column header is
            # blank. Bare day numbers ("1", "21st") are handled automatically.
            prayer_columns = {{                    # JAMAAT columns only
                Prayer.FAJR: "fajr",
                Prayer.DHUHR: "zuhr",
                Prayer.ASR: "asr",
                Prayer.MAGHRIB: "maghrib",
                Prayer.ISHA: "isha",
            }}
        ```

           The bases handle date parsing, am/pm inference, evidence and
           warnings — supply *configuration*, not parsing code. For site quirks
           override the `clean_cell` / `accept_row` hooks. Useful helpers:
           `helpers.times.coerce_time`, `helpers.dates.parse_date_flexible`,
           `helpers.html.find_table`, `helpers.relative.jamaat_after_start`
           (for "jamaat = adhan + N min").

        # Hard rules for the script

        - NEVER hardcode clock times, dates, or years; use `datetime.now().year`
          / the `dates` helpers for the current year.
        - NEVER invent rows — only emit times present in the source (one Jumuah
          listed -> one Jumuah row).
        - Only import: `datetime`, `re`,
          `uk_jamaat_directory.ingest.extract.helpers.*`,
          `...repo_extractors.contract`, `...repo_extractors.declarative`,
          `uk_jamaat_directory.domain`. No network/file libraries — the runtime
          fetches the targets and passes them in as artifacts.
        - Use the `.venv` for all Python invocations.

        # Finish

        Self-test (mandatory) — fix and re-run until it exits 0:

        `python -m uk_jamaat_directory.cli smoke-test-repo-extractor --extractor-key {extractor_key} --source-url {website_url}`

        Then write the result JSON to exactly `{result_path}` (the orchestrator
        reads only this file; missing/invalid -> failed):

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
        `{script_path}` failed validation (repair attempt {attempt}). Work
        alone — do NOT spawn subagents:

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
