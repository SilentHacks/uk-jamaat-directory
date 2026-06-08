# 0017: Overnight Extractor Authoring Orchestrator

## Status

Accepted. Builds on [ADR 0016](0016-repo-owned-extractor-scripts.md).
Amends ADR 0016's authoring hand-off: the AI step is now an end-to-end agent
session, not a deterministic link scorer.

## Context

ADR 0016 puts extractor scripts in the repository, but we still need a way to
author new scripts at scale. There are more than 1,800 `mosque_website` sources
in the directory and no extractor script for any of them today. Writing each
script by hand is not realistic; we want an overnight run that takes a list of
mosques and produces repo extractor scripts ready to commit.

The first design had the orchestrator do a deterministic link-scoring
"discovery" step on the source page, then ship a trimmed HTML sample to the
agent. In practice, that two-step flow was too brittle: the scorer made
decisions on insufficient context, the agent could only see a fragment, and
the agent was not allowed to navigate the site at all.

The orchestrator should instead hand the agent the source URL and let the
agent navigate the site autonomously. The agent is a sandboxed OpenCode session
with network access restricted (by prompt) to the source's registrable domain.
It discovers the timetable page, classifies the target kind, and either writes
a script or marks the source for human review.

## Decision

1. Introduce an `ExtractorAuthoringTask` row per source processed by the
   orchestrator. It records the source, status, discovered URL, target kind,
   script path, agent invocation outcome, validation issues, and timestamps.
2. The orchestrator's pre-flight does a single `fetch_url` on the source URL
   to confirm reachability and to record the content type the agent will see
   first. It does **not** do link scoring or classification; the agent does
   both.
3. Authoring is delegated to the OpenCode CLI as a subprocess
   (`opencode -m <model> run --format json <prompt>`). The orchestrator writes
   the prompt to a temp file, sets the working directory to the repo root so
   the agent can write to `ingest/extract/repo_extractors/scripts/`, and
   captures the JSON-event stream plus the trailing freeform summary.
4. The agent's prompt instructs it to:
   - Start at the source URL.
   - Navigate only the source's registrable domain (the prompt names it).
   - Find the prayer-timetable page, following links or trying common paths
     (`/prayer-times`, `/timetable`, `/salah`, `/namaz`, `/calendar`, etc.).
   - If the timetable is HTML, write a single Python file at the path the
     orchestrator pre-computed and emit a structured summary at the end.
   - If the timetable is a PDF, image, JSON, or JS-rendered page, do not write
     a script; emit a structured summary that records the discovery.
   - Never visit web.archive.org, third-party widgets, or unrelated domains.
5. The agent ends every run with a structured summary of the form:
   ```
   STATUS=authored|skipped_review|failed
   TARGET_URL=<url it actually used>
   TARGET_KIND=html|pdf|image|rendered_html|json
   SCRIPT_PATH=<path>      # only when STATUS=authored
   REASON=<short reason>   # only when STATUS=skipped_review or failed
   ```
   The orchestrator parses these lines from the last 1 KB of stdout.
6. For `STATUS=authored` the orchestrator reads the file the agent reported,
   runs `check_script_source` + `check_extractor(allowed_domain=...)`, writes
   the file to the canonical scripts directory (if not already there), then
   runs `sync_repo_extractors` to create the `SourceExtractorAssignment`.
7. For `STATUS=skipped_review` the orchestrator records the reason and the
   target kind. PDF, image, OCR, and JS-rendered targets land here until OCR
   is implemented.
8. For any other status (or no status reported), the task is marked
   `failed` with the agent's stdout/stderr excerpt.
9. Concurrency is bounded by an `asyncio.Semaphore` (`authoring_concurrency`,
   default 8). Each source has a per-source timeout
   (`authoring_per_source_timeout_seconds`, default 180s). The whole run has a
   global timeout (default 4h) and is safe to re-run; existing `deployed` and
   `awaiting_review` tasks are skipped.
10. The OpenCode CLI is treated as a black-box subprocess: a wrapper handles
    argv construction, prompt temp files, working directory, timeouts,
    stdout/stderr capture, and JSON-event parsing. There is no shared state,
    no live streaming, no tool-calling protocol.
11. The orchestrator is exposed as a CLI command (`orchestrate-authoring`), a
    Celery task (`authoring.run_overnight`), and an admin list endpoint
    (`GET /v1/admin/authoring`) for observability. No public endpoints.

## Network policy

The agent has network access. The prompt restricts it (by instruction, not by
sandbox) to the source's registrable domain. The orchestrator passes that
domain explicitly. If the agent ignores the restriction, the resulting script
will fail the `check_target_url` gate in `validator_post` and the task will be
marked `failed`. We accept that this is a soft policy for now; tightening it
to a real network sandbox is a follow-up.

## Consequences

- New `extractor_authoring_tasks` table for status and audit.
- New settings: `authoring_concurrency`, `authoring_per_source_timeout_seconds`,
  `authoring_global_timeout_seconds`, `ai_agent_model`, `ai_agent_base_url`
  (optional), `ai_agent_api_key` (optional).
- New CLI `orchestrate-authoring` (and `orchestrate-authoring --source-id` for
  one-off debugging).
- New Celery task `authoring.run_overnight` for scheduled runs.
- New admin endpoint `GET /v1/admin/authoring` for inspection.
- The deterministic link-scoring code is removed. Only a pre-flight fetch
  helper remains, to surface unreachable sources before the agent runs.
- The agent writes scripts directly into
  `ingest/extract/repo_extractors/scripts/`. The orchestrator validates and
  syncs; the developer reviews the git diff and commits.
- The orchestrator does not commit, push, or open PRs. That stays a developer
  responsibility.
- PDF / image / OCR / JS-rendered sources remain stuck on the review queue
  until OCR is implemented in a follow-up ADR.

## Out of scope

- OCR and PDF text extraction.
- A real network sandbox for the agent (the prompt is the only policy).
- PR automation via `gh`.
- Multi-tenant API key handling.
