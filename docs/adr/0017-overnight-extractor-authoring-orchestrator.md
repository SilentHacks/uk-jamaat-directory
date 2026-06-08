# 0017: Overnight Extractor Authoring Orchestrator

## Status

Accepted. Builds on [ADR 0016](0016-repo-owned-extractor-scripts.md).

## Context

ADR 0016 puts extractor scripts in the repository, but we still need a way to
author new scripts at scale. There are more than 1,800 `mosque_website` sources
in the directory and no extractor script for any of them today. Writing each
script by hand is not realistic; we want an overnight run that takes a list of
mosques, finds their prayer timetables, and produces repo extractor scripts
ready to commit.

The orchestrator must:

- Be polite to mosque websites (robots-aware, same-domain, bounded concurrency).
- Use the existing AI-extractor authoring prompt to keep output consistent
  with what humans would write.
- Skip targets that are not yet supported (PDF, image, OCR, JS-rendered) and
  push them to a review queue.
- Land authored scripts in the canonical `repo_extractors/scripts/` directory
  so the existing `sync_repo_extractors` and crawl pipeline can pick them up
  without further wiring.
- Be safe to run unattended: bounded concurrency, per-source and global
  timeouts, persistent task state, idempotent re-runs.

## Decision

1. Introduce an `ExtractorAuthoringTask` row per source processed by the
   orchestrator. It records the source, status, discovered URL, target kind,
   draft path, agent invocation outcome, validation issues, and timestamps.
2. Add a deterministic discovery step: fetch the source URL, score same-domain
   `<a href>` links for prayer-time keywords, pick the best candidate. If no
   candidate exists, fall back to the source URL itself.
3. Classify the target kind by HTTP `Content-Type`: `html`, `rendered_html`,
   `pdf`, `image`, `json`, or `unknown`.
4. Authoring is delegated to the OpenCode CLI as a subprocess
   (`opencode -m <model> run "<prompt>"`). The orchestrator builds the prompt
   using the existing `repo_extractors/authoring_prompt.build_authoring_prompt`
   plus a sample of the page (truncated to a small, safe size). The agent
   returns Python source, extracted from a ` ```python … ``` ` fence.
5. PDF, image, and unknown target kinds are **not** authored. They are marked
   `skipped_review` with reason `ocr not yet implemented` (or equivalent). No
   LLM call, no script written.
6. Validated HTML scripts are written to the canonical scripts directory and
   then `sync_repo_extractors` is called so the assignment is created in the
   database. The developer reviews the diff and commits the new script.
7. Concurrency is bounded by an `asyncio.Semaphore` (`authoring_concurrency`,
   default 8). Each source has a per-source timeout
   (`authoring_per_source_timeout_seconds`, default 120s). The whole run has a
   global timeout (default 4h) and is safe to re-run; existing `deployed` tasks
   are skipped.
8. The OpenCode CLI is treated as a black-box subprocess: a wrapper handles
   argv construction, prompt stdin or argv, timeouts, stdout/stderr capture, and
   retries (off by default). There is no shared state, no live streaming, no
   tool-calling protocol.
9. The orchestrator is exposed as a CLI command (`orchestrate-authoring`), a
   Celery task (`authoring.run_overnight`), and an admin list endpoint
   (`GET /v1/admin/authoring`) for observability. No public endpoints.
10. The agent only receives the source URL, the discovered target URL, and a
    HTML sample trimmed to a fixed cap. It never sees DB rows, raw artifacts,
    cookies, or unrelated pages.

## Consequences

- New `extractor_authoring_tasks` table for status and audit.
- New settings: `authoring_concurrency`, `authoring_per_source_timeout_seconds`,
  `authoring_global_timeout_seconds`, `authoring_drafts_dir`, `ai_agent_model`,
  `ai_agent_base_url` (optional), `ai_agent_api_key` (optional).
- New CLI `orchestrate-authoring` (and `orchestrate-authoring --source-id` for
  one-off debugging).
- New Celery task `authoring.run_overnight` for scheduled runs.
- New admin endpoint `GET /v1/admin/authoring` for inspection.
- Scripts authored by the orchestrator land in the canonical scripts directory
  and become valid targets for `sync_repo_extractors` immediately. The
  developer must review the git diff before the next `process-source` run picks
  them up.
- The orchestrator does not commit, push, or open PRs. That stays a developer
  responsibility.
- PDF / image / OCR sources remain stuck on the review queue until OCR is
  implemented in a follow-up ADR.

## Out of scope

- OCR and PDF text extraction.
- Browser-rendered HTML (`requires_javascript=True`).
- PR automation via `gh`.
- LLM-driven link discovery (deterministic scoring only).
- Multi-tenant API key handling.
