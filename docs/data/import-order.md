# Data import order

Recommended sequence for populating mosque identity in production. Applies to
both the live acquisition commands and the offline synthetic fixtures used in
tests.

## 1. OpenStreetMap (first)

Export UK and Ireland Muslim places of worship from Overpass, then import into
Postgres. OSM is imported first so that subsequent identity matchers have a
canonical set of mosque rows to link against instead of creating duplicates.

```bash
uk-jamaat-directory export-osm --output data/exports/osm_uk_ie_muslim.json
uk-jamaat-directory import-osm --input data/exports/osm_uk_ie_muslim.json
```

OSM supplies canonical UK and Ireland coverage for names, coordinates,
postcodes / Eircodes, and website URLs where tagged. Imported rows use
`publication_policy=public_redistribution_allowed` and ODbL attribution. See
[ATTRIBUTION.md](../../ATTRIBUTION.md).

For offline development, use `data/fixtures/openstreetmap/sample_places.json`
instead of a live export.

### Captured OSM provenance

The OSM mapper and query are configured to retain per-record provenance on the
source row:

- `source_record_updated_at` from the OSM element `timestamp` (`out center meta`).
- `osm_version`, `osm_changeset`, `osm_user` from the same element metadata.

These fields feed the date-driven name precedence rule used by the identity
resolver (see *Identity matching* below) and let operators audit which OSM
element a given row was sourced from.

## 2. MuslimsInBritain (second)

Import MiB after OSM so identity matching can link MiB records to existing
OSM-created mosques rather than creating duplicates. MiB import covers the full
MuslimsInBritain UK and Ireland scope.

```bash
# Lightweight refresh: CSV only, no per-record detail enrichment.
uk-jamaat-directory export-mib --output data/exports/mib_uk_ie_mosques.json
uk-jamaat-directory import-mib --input data/exports/mib_uk_ie_mosques.json
uk-jamaat-directory report-mib

# Full refresh: follow each MiB record to its detail page to capture
# Last Updated, phone, website, capacity, theme, data accuracy, and
# upstream source list. Slower (~5–8 min for ~2,100 records at the
# current throttle) but the recommended cadence for an identity refresh.
uk-jamaat-directory export-mib --enrich-details \
    --output data/exports/mib_uk_ie_mosques.json
uk-jamaat-directory import-mib --input data/exports/mib_uk_ie_mosques.json
uk-jamaat-directory report-mib
```

MiB rows default to `publication_policy=public_redistribution_allowed` under
[ADR 0011](../adr/0011-muslimsinbritain-import-policy.md) (decision recorded
2026-06-06). Name, address, postcode, city, country, website, phone, capacity,
theme, management, and data accuracy may flow into the public `mosques` row
and into the public API / bulk exports under the standard
`public_redistribution_allowed` gate. Public consumers must credit
`MuslimsInBritain.org` and link to the per-row `source_url` when redistributing.

The existing field-level overwrite rules still apply: when an MiB record
auto-links to an OSM-created mosque, fields are written with
`only_empty=True` (see `src/uk_jamaat_directory/ingest/discovery/resolve.py`),
so an OSM website is never overwritten by an MiB website.

For historical data already in the database, run the one-shot backfill:

```
uk-jamaat-directory backfill-mib-websites [--dry-run]
```

This walks MiB sources with `metadata_.website_url`, joins to their linked
mosque, and sets `mosques.website_url` only where it is currently null or empty.

The backfill promotes websites only; it does not change the source's
`publication_policy`. Historical MiB sources imported before ADR 0011 still
have `publication_policy=unknown`, so their mosques stay out of the public
export even after the backfill. To make the new websites visible, also flip
the existing MiB source policies (e.g. with a one-shot SQL update, after
auditing the source list).
It honours the same `only_empty` rule as the import path and reports a count
of `updated` / `skipped_already_set` / `skipped_no_mosque` / `errors`.

Operators that prefer a conservative read-only posture can override the default
with `MUSLIMSINBRITAIN_PUBLICATION_POLICY=unknown` (or the per-CLI
`--publication-policy unknown` flag) and MiB data will stay in
`mosque_sources.metadata_` without flowing into the public mosque row.

### MiB record classes and expected gaps

MiB records are tagged with a `record_class` (`mosque`, `hired_hall`, or
`prayer_room`) and a `location_precision` (`precise`, `approximate`, or
`unknown`). `hired_hall` and `prayer_room` records are expected to frequently
lack a postcode and a precise coordinate; the matcher does not treat their
absence as an identity signal.

### Captured MiB provenance

The MiB bundle carries per-record fields on the source row:

- `detail_page_url` — link to the upstream `show-mosque.php?id=…&map` page.
- `source_record_created_at` and `source_record_updated_at` — extracted from
  the detail page (`Last Updated:` field, `DD/MM/YYYY`). Drives the date-driven
  name precedence rule.
- `data_accuracy` and `data_accuracy_code` (`A`–`F`) — self-reported
  confidence on the upstream page.
- `data_sources` — list of upstream attribution strings the mosque supplied
  on the detail page.
- `phone`, `website_url`, `capacity`, `theme` — additional fields populated by
  the detail-page enrichment pass.

### Acquisition behaviour

- The CSV fetch retries transient transport errors (3 attempts, 1 s sleep
  between attempts; 5xx responses also retried). It still raises on
  non-recoverable status codes so that a broken upstream surfaces in CI.
- The detail-page enrichment pass runs with bounded concurrency
  (`DETAIL_CONCURRENCY=3`, `DETAIL_REQUEST_DELAY_SECONDS=0.35` per request) to
  avoid overwhelming the upstream site. Each detail page is fetched with the
  project crawl user agent.
- The bundle is validated by the `MibImportBundle` schema and the
  `validate_mib_bundle` rules before it is written. Validation failures abort
  the export with a clear error rather than producing a partial file.

## 3. Review and merge

After each import run, inspect the new state and triage the new pending
identity reviews before downstream crawl or timetable work:

```bash
uk-jamaat-directory identity-report
uk-jamaat-directory list-identity-reviews --limit 50
uk-jamaat-directory report-mib
```

Reviews are generated by the matcher (not silently auto-linked) when a record
plausibly matches an existing mosque but the evidence is not strong enough to
merge. Common reasons for landing in review:

- Geo is close (≤ 150 m) and postcode or name disagrees.
- Name is near-identical but the postcode or geo is far enough apart to be
  ambiguous.
- The MiB record is `hired_hall` / `prayer_room` with low
  `metadata_confidence` — the matcher keeps these in review even with a
  plausible geo match.

### Identity matching strategy

The shared identity matcher (`ingest.discovery.matching`) scores every
candidate pair against an existing mosque on three axes:

1. **Name signals** — token overlap ratio, alias coverage via
   `fuzz.token_sort_ratio`, and near-matches against existing aliases.
2. **Postcode / Eircode signals** — exact match, post-code-area match, or
   Eircode routing-key match.
3. **Geo signals** — graduated distance bands. A pair within 25 m is treated
   as a strong identity signal that can override a postcode mismatch;
   25–150 m is a supporting signal; 150–500 m is a candidate signal only.

A pair is auto-linked when the combined score meets `AUTO_LINK_THRESHOLD=0.75`
and at least one strong identity signal is present (domain match, strong name
ratio, or a 25 m geo hit). Anything below the threshold but above the
candidate floor is recorded as a pending `identity_match_review` with the
candidate score preserved so reviewers can see what the matcher saw.

### Re-import behaviour

Re-running `import-osm` or `import-mib` against an updated export is
idempotent on the source rows but performs two important housekeeping steps:

- **Pending reviews for the source are accepted** if the new run would auto-link
  the same pair again. This prevents a successful re-import from leaving
  stale "needs review" rows that an operator previously deferred.
- **Source rows with no matching record in the new export are not deleted.**
  They are kept as `stale` and surface in the freshness report; removal is an
  operator decision.

## 4. Date-driven name precedence

When two source rows disagree on a canonical field (typically the public
mosque name), the resolver prefers the newer source-provided record date. The
date sources are, in priority order:

1. `source_record_updated_at` on the source row (from OSM `timestamp` or MiB
   detail-page `Last Updated`).
2. `source_record_created_at` on the source row.
3. The bundle `exported_at` is **not** used for name precedence — it only
   records when the bundle was generated.

This rule is what stops a stale OSM row from re-overwriting a canonical name
that a more recent MiB record updated, and vice versa. It only applies inside
the `publication_policy` boundary defined in
[ADR 0003](../adr/0003-source-publication-gates.md) — a source with
`publication_policy=unknown` cannot currently replace a public canonical field.

## Refresh cadence

Both `export-osm` and `export-mib` are run manually today; scheduled refresh
jobs are deferred to later observability work. The recommended cadence is:

- **OSM** — quarterly, or when coverage of a new region is needed.
- **MiB** — quarterly, with `--enrich-details` so `Last Updated`,
  `data_accuracy`, and the new detail fields stay current.

After every refresh, re-run `identity-report` and `report-mib` to confirm the
expected deltas (new auto-links, accepted stale reviews, and the residual
review backlog) match the change.
