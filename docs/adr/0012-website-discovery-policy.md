# 0012: Phase 5 Website Discovery Policy

## Status

Accepted (2026-06-06).

## Context

Phase 5 of the remaining data pipeline asks the Directory to fill in
missing `mosque.website_url` fields. ADR 0005 already rules out Google-derived
facts as public provenance, but leaves room for private lead generation. The
plan §5 also asks for "cheaper non-search heuristics" alongside any search
APIs.

We want to do this for free, without paid data brokers, and we want a clear
audit trail for every URL written to a public row.

## Decision

Phase 5 uses a **provider-and-gate** model:

1. A small set of **free public** providers propose candidate URLs:
   - `mib_metadata` — walk `mosque_sources.metadata_` for homepage fields the
     backfill did not promote (Tier 1a, no network, implemented first).
   - `osm_tag_recheck` — re-parse OSM `website` / `contact:website` / `url`
     tags from the existing `data/exports/osm_*.json` bundle (Tier 1b, no
     network, planned next).
   - `charity_commission` — bulk-download the daily Charity Commission
     register extract (England & Wales) and the OSCR Scottish register, and
     join by name + postcode (Tier 1c, free public dataset, planned).
    - `wikidata` — single SPARQL query for UK mosques with `P856` (official
      website) (Tier 1d, free, planned — dropped due to sparse coverage).
    - `search_engine` — Exa.ai search API, quoted-name + postcode query per
      mosque (Tier 2, free tier 1,000 req/month). Leads are **not**
      public-linked and must pass live HTTP + name + postcode verification.
 2. The verification gate promotes a candidate to `mosque.website_url` only
    if **either**:
    - the URL was found in a public, redistributable source already linked to
      the mosque (`mib_metadata`, `osm_tag_recheck`, `charity_commission`,
      `oscr`); **or**
    - a live HTTP fetch returns 200/text-html, the page `<title>` / first H1
      contains the normalised mosque name (token-set fuzzy match ≥ 60), and at
      least one of postcode or address appears in the visible text.
 3. Failed candidates are recorded as `AdminDiscoveryLead` audit rows (the
    existing admin-only mechanism), never promoted.
 4. Promotions are written through the existing `SourceType.MANUAL` source
    path with a per-provider attribution string. The new manual source row
    has `publication_policy=public_redistribution_allowed` so the website
    reaches the public export.
 5. Search-engine discovery is **opt-in** (`--provider search_engine`, off by
    default) and rate-limited (`search_engine_delay_seconds`, default 1.0 s).
    Results are cached locally for 30 days to avoid burning API quota.
 6. Companies House lookups are out of scope for v1.
 7. No URL found via a search engine, scraping, or non-public directory is
    ever written as a public fact without operator sign-off.

## Consequences

- The Phase 5 work is bounded to free public data sources, matching the
  project's no-paid-data-brokers policy.
- Every promoted URL has a clean provenance: a `SourceType.MANUAL` row with
  `attribution`, `discovery_provider`, `discovery_reason`, and
  `discovery_verification` in `metadata_`. The public export sees the
  website; operators can audit the source.
- Failed candidates show up in the same `discovery_lead` audit table as
  Google leads, with `provider` set to the actual source (e.g. `mib_metadata`).
- The verification gate is moderate, not strict: a MiB-linked URL bypasses
  the network check, but a search-engine result must clear the live
  page-name-and-postcode match. This trades a small amount of false
  positives (one-off linked URLs) for a much higher recall on real
  mosques that have no other online footprint.
- DuckDuckGo scraping is gated behind a flag and rate-limited, so the
  default operator experience is fully consistent with ADR 0005 and the
  data licence docs.

## Follow-ups

- Implement the OSM tag re-check, Charity Commission bulk join, and
  Wikidata SPARQL providers.
- Add metrics: candidates proposed, verified, promoted, denied, and
  leads recorded per provider, surfaced via the admin reporting API.
- Investigate whether the Wikidata query should be expanded to include
  P31=mosque OR P31=place_of_worship for UK (the strict P31=mosque filter
  returns almost no results today).
