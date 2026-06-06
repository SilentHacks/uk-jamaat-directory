# 0015: AI Extraction Profiles

## Status

Accepted.

## Context

Phase 7 of the data pipeline requires automated reconnaissance of mosque websites to locate
prayer timetables and determine the best extraction strategy. Manual inspection of ~1,000+
mosque websites is not operationally viable. AI-assisted profiling can inspect HTML snippets,
identify timetable assets (tables, lists, PDFs, images), and suggest extraction strategies
with confidence scores.

The project already has:
- `mosque_website` sources registered from `website_url` (Phase 6).
- `extraction_runs` and `source_artifacts` tables for audit trails.
- `ExtractionKind.AI` enum value and validation gates (`ai_requires_review`).
- No existing LLM client or extraction profile schema.

## Decision

1. **Groq + llama-3.1-8b-instant** — Use Groq's hosted inference API with the
   `llama-3.1-8b-instant` model for reconnaissance profiling. Rationale:
   - Low latency and cost suitable for batch profiling.
   - No local GPU or model hosting required.
   - JSON mode (`response_format: {type: "json_object"}`) enables strict structured output.
   - 30 RPM free-tier limit is acceptable for the current scale.

2. **Scope: profile-only** — Phase 7 AI is limited to *reconnaissance profiling*:
   discovering where timetables live, what asset type they are, and how they might be
   extracted. Actual row extraction from HTML/PDF/OCR is deferred to Phase 8
   deterministic extractors.

3. **Token bounding** — Every profiling request is bounded:
   - Max 6 pages fetched per source (homepage + 5 common paths).
   - Each page truncated to 50,000 characters before prompt construction.
   - `max_tokens=4096` on the LLM response.
   - No images, PDFs, or binary assets are sent to the LLM in Phase 7.

4. **Rate limiting** — A module-singleton async token-bucket limiter enforces the global
   30 RPM ceiling (1 token per 2 seconds, burst of 5). The Groq client acquires a token
   before every request. One retry on HTTP 429; after that, the error surfaces to the
   caller.

5. **Global gate, default enabled** — `ai_profiling_enabled` defaults to `True` in
   settings. A missing `groq_api_key` causes graceful skip with a clear error.
   No per-source opt-in is required for the MVP.

6. **Profile status workflow** — After profiling, each source receives:
   - `profile_status = "ready"` if `confidence >= 0.8` and `asset_type != "unknown"`.
   - `profile_status = "review_needed"` otherwise.
   - `extraction_profile` stored in `source.metadata_`.
   - `ExtractionRun` row created with `kind=AI`, `score=confidence`, and audit metadata.

7. **Human review required** — No AI-derived profile is trusted for scheduled
   deterministic extraction until a human reviewer has inspected it. The existing
   `publish_allow_ai=False` default also blocks any downstream publishing of AI-extracted
   candidates.

8. **Privacy acknowledgment** — Truncated HTML snippets are sent to Groq, a US-hosted
   third-party API. Operators must be aware that mosque website content leaves the
   project's infrastructure during profiling. No personal data, contact details, or
   claim/correction content is included in prompts.

## Consequences

- `profile-source --source-id <uuid>` and `profile-sources [--limit N]` CLI commands
  allow operators to run batch profiling.
- `POST /v1/admin/sources/{source_id}/profile` and `GET …/profile` API endpoints
  expose profiling to the admin UI (Phase 10).
- Profiling does not create `schedule_candidates`. It only updates source metadata.
- Re-profiling is manual (CLI or API) for this phase. No automatic re-run hooks.
- If Groq is unavailable or rate-limited, profiling fails gracefully and records
  the failure in `ExtractionRun` metadata for operator review.
- Future model upgrades (e.g., `llama-3.3-70b-versatile`) can be adopted by changing
  `ai_model` in settings without code changes.
