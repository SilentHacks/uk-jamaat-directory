# 0014: Retire Standard Feed (Well-Known JSON)

## Status

Accepted. Supersedes decisions #1 and standard_feed-specific policy in ADR 0007.

## Context

The original crawl strategy ([ADR 0007](0007-crawl-artifacts-extraction.md)) proposed a
feed-first approach: prefer `/.well-known/uk-jamaat-directory.json` on the mosque domain
before attempting HTML scraping. This assumed mosque websites or CMS platforms would
adopt a machine-readable timetable endpoint at a well-known path.

In practice, the vast majority of mosque websites do not and will not publish a
JSON timetable at `/.well-known/uk-jamaat-directory.json`. The convention has no
ecosystem adoption, no CMS plugin, and no operator incentive to create one.

## Decision

1. **Retire the well-known JSON feed entirely.** No code path fetches, parses, or
   creates `standard_feed` source rows.

2. **Delete the following:**

   | Item | Path |
   |------|------|
   | Standard feed extractor package | `src/uk_jamaat_directory/ingest/extract/standard_feed/` |
   | Feed spec doc | `docs/feeds/standard-feed-v1.md` |
   | Synthetic JSON fixtures | `data/fixtures/crawl/standard_feed_valid.json`, `_invalid.json` |
   | Extractor unit tests | `tests/test_standard_feed_extractor.py` |
   | `fetch-feed` CLI command | `cli.py` |
   | `SourceType.STANDARD_FEED` | `domain.py` |
   | `standard_feed_path` config | `config.py` |

3. **Migrate existing DB rows.** Alembic 005 converts any `standard_feed` rows in
   `mosque_sources` to `mosque_website` (with `migrated_from` metadata), or deletes
   them if the mosque already has a `mosque_website` source. The PostgreSQL enum value
   remains as a documented dead value to avoid type-recreation risk.

4. **Post-migration crawl path:** `mosque_website` → AI profile (Phase 7) →
   deterministic extraction (Phase 8). No JSON feed step.

## Consequences

- Registration is simpler: `ensure_crawl_sources()` always creates `MOSQUE_WEBSITE`.
- ~1,300+ fewer HTTP probes per registration run (was a 40+ minute bottleneck with
  the feed probe).
- MLM remains the only structured feed import path.
- If a future need arises for mosques to self-publish machine-readable timetables,
  that is a new provider/discovery path, not a registration-time probe.
