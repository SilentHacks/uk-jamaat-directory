# 0016: Repo-Owned Extractor Scripts

## Status

Accepted. Supersedes [ADR 0015](0015-ai-extraction-profiles.md) and amends
[ADR 0007](0007-crawl-artifacts-extraction.md).

## Context

The previous Phase 7 approach stored AI-discovered extraction metadata in
`mosque_sources.metadata["extraction_profile"]`. That approach is too brittle for the
variance found across mosque websites: tables, lists, PDFs, images, JavaScript widgets,
typos, relative rules, and site-specific phrasing do not fit reliably into one generic
database recipe.

The project still needs deterministic scheduled extraction. The useful AI step is not a
runtime parser; it is authoring and maintaining source-specific deterministic parser code.

## Decision

1. Extraction logic for mosque websites lives in version-controlled Python modules under
   the application source tree, not in database JSON.
2. AI agents may author or edit these modules as normal repository changes. Community
   contributors can review, test, and patch them through the same workflow as other code.
3. The database stores only operational assignment state: which extractor key applies to a
   source, current version, status, scheduling cadence, health, and last error.
4. The cutover is hard. Runtime code must not fall back to
   `mosque_sources.metadata["extraction_profile"]`.
5. Scheduled runtime is deterministic and non-AI. Extractor modules receive framework-fetched
   artifacts and return standardized rows; they do not call LLMs.
6. Extractor modules must not fetch network resources directly. The framework fetches every
   declared target URL through the existing crawl security, robots, timeout, size, and
   throttling controls.
7. Passing gates are sufficient for activation: static import checks, capability checks,
   sandbox execution, output contract validation, and schedule candidate validation. No
   additional human review gate is required.
8. Third-party embedded timetable widgets remain blocked unless they are later modeled as an
   explicit source with an approved publication policy.
9. PDF, OCR, image, and browser-rendered extraction must use shared helper modules. Site
   scripts should stay thin and site-specific.
10. Gate-passed deterministic repo extractor candidates may auto-approve after validation
    when configured. Source publication policy still controls public publication.

## Consequences

- `profile-agent-sources` and admin profile endpoints are retired.
- New `mosque_website` sources no longer receive profile metadata.
- A new `source_extractor_assignments` table drives scheduled website extraction.
- Scripts under `repo_extractors/scripts/` become public, reviewable operational logic.
- Deployment must run extractor validation and assignment sync after migrations.
- Public APIs and exports remain protected by the existing candidate validation,
  approval, dataset publication, and source publication policy gates.
