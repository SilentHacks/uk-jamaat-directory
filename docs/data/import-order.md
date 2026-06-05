# Data import order

Recommended sequence for populating mosque identity in production.

## 1. OpenStreetMap (first)

Export UK and Ireland Muslim places of worship from Overpass, then import into Postgres:

```bash
uk-jamaat-directory export-osm --output data/exports/osm_uk_ie_muslim.json
uk-jamaat-directory import-osm --input data/exports/osm_uk_ie_muslim.json
```

OSM supplies canonical UK and Ireland coverage for names, coordinates, postcodes/Eircodes, and website URLs where tagged. Imported rows use `public_redistribution_allowed` and ODbL attribution. See [ATTRIBUTION.md](../../ATTRIBUTION.md).

For offline development, use `data/fixtures/openstreetmap/sample_places.json` instead of a live export.

## 2. MuslimsInBritain (second)

Import MiB after OSM so identity matching can link MiB records to existing OSM-created mosques rather than creating duplicates. MiB import covers the full MuslimsInBritain UK and Ireland scope.

```bash
uk-jamaat-directory export-mib --output data/exports/mib_uk_ie_mosques.json
uk-jamaat-directory import-mib --input data/exports/mib_uk_ie_mosques.json
uk-jamaat-directory report-mib
```

MiB rows default to `publication_policy=unknown` under [ADR 0011](../adr/0011-muslimsinbritain-import-policy.md). They are available for private identity review and source overlap, but do not enter public APIs or exports unless their source policy is explicitly upgraded.

## 3. Review and merge

Review `identity_match_reviews` and duplicate candidates before large downstream crawl or timetable work.

## Refresh cadence

Re-run `export-osm` and `import-osm` manually when refreshing OSM identity. Scheduled refresh jobs are deferred to later observability work.
