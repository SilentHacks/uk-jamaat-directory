# ADR 0011: MuslimsInBritain Import Policy

## Status

Accepted. Last updated 2026-06-06: redistribution decision recorded below.

## Context

MuslimsInBritain.org maintains a UK and Ireland mosque directory with location,
identity, facility, usage, theme, management, and status metadata. The directory
does not provide jamaat times or a stable public API, but it does provide POI/CSV
downloads intended for navigation devices.

The MiB site states that material on the mosque directory is drawn from the
public domain and may be reproduced, preferably with appropriate acknowledgement.
The Directory still needs an explicit publication-policy decision before MiB
facts enter public APIs or exports.

## Decision

MiB is imported as an identity/discovery source across the full UK and Ireland
scope. It is not used for timetable data.

### Redistribution decision (2026-06-06)

MiB sources default to `publication_policy=public_redistribution_allowed` for new
imports. Operators may import and match MiB records privately, and MiB-derived
fields (name, address, postcode, city, country, website, phone, capacity,
theme, management, data accuracy, and `source_record_updated_at`) may flow into
the public `mosques` row, the public API, and bulk exports under the standard
`public_redistribution_allowed` gate.

The MiB site states that material on the mosque directory is drawn from the
public domain and may be reproduced, preferably with appropriate acknowledgement.
Public consumers must credit `MuslimsInBritain.org` and link to the per-row
`source_url` when a row's data is redistributed. The Directory's existing
attribution framework ([`ATTRIBUTION.md`](../../ATTRIBUTION.md)) and
`exports.collect._build_attribution()` cover this automatically.

The existing field-level overwrite rules still apply: when an MiB record
auto-links to an OSM-created mosque, fields are written with `only_empty=True`
(`src/uk_jamaat_directory/ingest/discovery/resolve.py:121`), so a website
sourced from OSM is never overwritten by an MiB website. The companion
`backfill-mib-websites` CLI exposes the same rule for the historical data
(see [docs/data/import-order.md](../data/import-order.md)).

### Earlier interim position

The previous default of `publication_policy=unknown` is preserved as a
configuration override: operators that prefer a conservative read-only posture
can set `MUSLIMSINBRITAIN_PUBLICATION_POLICY=unknown` (or the per-CLI
`--publication-policy` flag) and MiB data will stay in `mosque_sources.metadata_`
without flowing into the public mosque row.

The importer uses the MiB CSV/POI download as the acquisition source and records
per-row source URLs using MiB IDs. Acquisition has two stages:

1. The CSV download (`gps-csv.php?includecomment=1`) is fetched with retry
   on transient transport errors (3 attempts, 1 s sleep). 4xx responses fail
   loudly so a broken upstream surfaces in CI.
2. An opt-in detail-page enrichment pass (`export-mib --enrich-details`)
   follows each record to its `show-mosque.php?id=…&map` page to capture
   `Last Updated`, `Phone`, `Website`, `Capacity`, `Theme`, `Data Accuracy`
   (with `A`–`F` code), and `Source(s)`. The pass is rate-limited:
   `DETAIL_CONCURRENCY=3` concurrent requests with a
   `DETAIL_REQUEST_DELAY_SECONDS=0.35` per-request sleep, using the project
   crawl user agent. This is intentionally polite to avoid triggering
   upstream rate-limits; a higher-concurrency fetch caused upstream
   `connection refused` responses during development and was rolled back.

Per-row MiB records carry `detail_page_url`, `source_record_created_at`,
`source_record_updated_at`, `data_accuracy`, `data_accuracy_code`, and
`data_sources` on the source row. `source_record_updated_at` is the field
that drives the date-driven name-precedence rule in
[`docs/data/import-order.md`](../data/import-order.md); the bundle
`exported_at` is intentionally not used for that purpose.

Raw live downloads must not be committed. Synthetic fixtures live under
`data/fixtures/muslimsinbritain/` and are used for tests only.

## Consequences

- MiB can improve identity coverage and source overlap after OSM import.
- MiB-derived facts remain private by default under ADR 0003 gates.
- Attribution guidance is recorded in `ATTRIBUTION.md`.
- Any future decision to publish MiB-only facts must update this ADR with the
  effective terms and acknowledgement text.
