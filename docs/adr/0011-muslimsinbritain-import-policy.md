# ADR 0011: MuslimsInBritain Import Policy

## Status

Accepted

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

MiB sources default to `publication_policy=unknown`. Operators may import and
match MiB records privately, but public APIs and exports must not expose MiB-only
facts until the source policy is explicitly upgraded to
`public_redistribution_allowed`.

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
