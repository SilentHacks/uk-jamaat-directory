# Data import order

Recommended sequence for populating mosque identity in production.

## 1. OpenStreetMap (first)

Export GB Muslim places of worship from Overpass, then import into Postgres:

```bash
uk-jamaat-directory export-osm --output data/exports/osm_gb_muslim.json
uk-jamaat-directory import-osm --input data/exports/osm_gb_muslim.json
```

OSM supplies canonical GB coverage for names, coordinates, postcodes, and website URLs where tagged. Imported rows use `public_redistribution_allowed` and ODbL attribution. See [ATTRIBUTION.md](../../ATTRIBUTION.md).

For offline development, use `data/fixtures/openstreetmap/sample_places.json` instead of a live export.

## 2. MuslimsInBritain (second)

Import MiB after OSM so identity matching can link MiB records to existing OSM-created mosques rather than creating duplicates. MiB import is Phase 3 work (`import-mib`).

## 3. Review and merge

Review `identity_match_reviews` and duplicate candidates before large downstream crawl or timetable work.

## Refresh cadence

Re-run `export-osm` and `import-osm` manually when refreshing OSM identity. Scheduled refresh jobs are deferred to later observability work.
