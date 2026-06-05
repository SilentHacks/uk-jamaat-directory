# 0007: Crawl, Artifacts, And Extraction

## Status

Accepted.

## Context

Most UK mosques are expected to come from MyLocalMasjid or other partner feeds when licensed. A long tail still publishes jamaat times only on mosque-owned websites. Phase 9 adds a respectful fetch → artifact → extract pipeline that feeds the existing candidate validation and publication workflow.

## Decision

1. **Feed-first** — prefer `/.well-known/uk-jamaat-directory.json` on the mosque domain before HTML/PDF scraping (HTML scraping deferred to slice 9.2).

2. **MyLocalMasjid excluded** — Phase 9 does not crawl MLM. MLM remains the Phase 5 import adapter (`import-mlm`).

3. **Private artifacts** — raw fetched bytes live in object storage; database rows store metadata and content hashes only.

4. **Respectful fetch** — robots.txt checks, conditional GET (ETag/Last-Modified), response size limits, per-source backoff, and opt-in `CRAWL_ENABLED`.

5. **Default source policy** — auto-created `standard_feed` sources use `publication_policy=unknown` until an admin sets redistribution terms.

6. **Manual approval for website-derived candidates** — `standard_feed` and `mosque_website` candidates stay `pending` after validation until explicitly approved, even when validation passes.

7. **Deferred extractors** — HTML table parsing, PDF/OCR, Playwright, and AI extraction are later slices within Phase 9.

## Consequences

- Operators enable crawl explicitly, register sources, review candidates, set publication policy, approve, then publish.
- Celery beat schedules source registration and hourly due fetches when workers are running.
- Golden HTML/PDF fixtures are required before auto-approval can be considered for scraped sources.
