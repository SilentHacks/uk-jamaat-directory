# 0007: Crawl, Artifacts, And Extraction

## Status

Amended by [ADR 0014](0014-retire-standard-feed.md) and
[ADR 0016](0016-repo-owned-extractor-scripts.md). Decisions #1 and
standard_feed-specific references in #5 and #6 are superseded. Decision #6 is amended so
gate-passed repo-owned deterministic website extractors may auto-approve candidates when
configured.

## Context

Most UK mosques are expected to come from MyLocalMasjid or other partner feeds when licensed. A long tail still publishes jamaat times only on mosque-owned websites. Phase 9 adds a respectful fetch → artifact → extract pipeline that feeds the existing candidate validation and publication workflow.

## Decision

1. **Mosque website first** — register `mosque_website` sources from `mosque.website_url`; fetch homepage HTML. The well-known JSON feed (`/.well-known/uk-jamaat-directory.json`) was considered but deemed not viable (ADR 0014).

2. **MyLocalMasjid excluded** — Phase 9 does not crawl MLM. MLM remains the Phase 5 import adapter (`import-mlm`).

3. **Private artifacts** — raw fetched bytes live in object storage; database rows store metadata and content hashes only.

4. **Respectful fetch** — robots.txt checks, conditional GET (ETag/Last-Modified), response size limits, per-source backoff, and opt-in `CRAWL_ENABLED`.

5. **Default source policy** — auto-created `mosque_website` sources use `publication_policy=unknown` until an admin sets redistribution terms.

6. **Manual approval for website-derived candidates** — `mosque_website` candidates stay `pending` after validation until explicitly approved, even when validation passes.

7. **Deferred extractors** — HTML table parsing, PDF/OCR, Playwright, and AI extraction are later phases (Phase 7/8).

## Consequences

- Operators enable crawl explicitly, register sources, review candidates, set publication policy, approve, then publish.
- Celery beat schedules source registration and hourly due fetches when workers are running.
- Golden HTML/PDF fixtures are required before auto-approval can be considered for scraped sources.
