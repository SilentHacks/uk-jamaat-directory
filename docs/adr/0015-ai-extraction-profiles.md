# 0015: AI Extraction Profiles

## Status

Accepted.

## Context

Phase 7 of the data pipeline requires automated reconnaissance of mosque websites to locate
prayer timetables and determine the best extraction strategy. Manual inspection of ~1,000+
mosque websites is not operationally viable. AI-assisted profiling can navigate websites,
identify timetable assets (tables, lists, PDFs, images), and suggest extraction strategies
with confidence scores.

The project already has:
- `mosque_website` sources registered from `website_url` (Phase 6).
- `extraction_runs` and `source_artifacts` tables for audit trails.
- `ExtractionKind.AI` enum value and validation gates (`ai_requires_review`).

## Decision

1. **Autonomous agents via OpenCode** — Use `opencode` CLI subprocesses with
   `deepseek-v4-flash` (or operator-configured model) for reconnaissance profiling.
   Each agent receives a system prompt with task, constraints, and output schema,
   then autonomously navigates the target mosque website using `webfetch`.
   Rationale:
   - Agents can follow links and discover timetable pages beyond static probe paths.
   - No single-shot prompt size limits (agent manages its own context).
   - Cost is acceptable at current scale (~2,420 mosques with websites).
   - HTML snippets leave the project's infrastructure only during agent execution.

2. **Scope: profile-only** — Phase 7 AI is limited to *reconnaissance profiling*:
   discovering where timetables live, what asset type they are, and how they might be
   extracted. Actual row extraction from HTML/PDF/OCR is deferred to Phase 8
   deterministic extractors.

3. **Page budget** — Every profiling request is bounded:
   - Max 10 pages fetched per source (configurable via `ai_agent_max_pages`).
   - Agent must self-track visited URLs and stop when the limit is reached.
   - No images, PDFs, or binary assets are sent to the LLM in Phase 7.

4. **Orchestration** — A Python asyncio orchestrator spawns agent subprocesses,
   enforces per-agent timeouts (default 120s), limits concurrency (default 3),
   and collects JSON result files from disk. State is persisted in `state.json`
   for resumability.

5. **Global gate, default enabled** — `ai_profiling_enabled` defaults to `True` in
   settings. A missing `opencode` installation causes graceful failure with a clear error.
   No per-source opt-in is required for the MVP.

6. **Profile status workflow** — After profiling, each source receives:
   - `profile_status = "ready"` if `found=true`, `confidence >= 0.8`, and `asset_type != "unknown"`.
   - `profile_status = "review_needed"` otherwise.
   - `extraction_profile` stored in `source.metadata_`.
   - `ExtractionRun` row created with `kind=AI`, `score=confidence`, and audit metadata.

7. **Human review required** — No AI-derived profile is trusted for scheduled
   deterministic extraction until a human reviewer has inspected it. The existing
   `publish_allow_ai=False` default also blocks any downstream publishing of AI-extracted
   candidates.

8. **Privacy acknowledgment** — HTML page content is sent to the agent's LLM provider
   during profiling. Operators must be aware that mosque website content leaves the
   project's infrastructure during agent execution. No personal data, contact details, or
   claim/correction content is included in prompts.

## Consequences

- `profile-agent-sources [--limit N] [--concurrency N] [--timeout N]` CLI command
  allows operators to run batch profiling with autonomous agents.
- `POST /v1/admin/sources/{source_id}/profile` and `GET …/profile` API endpoints
  expose profiling to the admin UI (Phase 10). The POST endpoint now triggers a single
  agent subprocess.
- Profiling does not create `schedule_candidates`. It only updates source metadata.
- Re-profiling is manual (CLI or API) for this phase. No automatic re-run hooks.
- If an agent times out or fails, the orchestrator records the failure in
  `ExtractionRun` metadata for operator review.
- Future model changes can be adopted by changing `ai_agent_model` in settings.
