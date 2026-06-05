# OpenStreetMap fixtures

Synthetic fixtures for OSM import and export tests across the UK and Ireland. Do not commit live Overpass exports.

| File | Purpose |
|------|---------|
| `sample_places.json` | Normalized `OsmImportBundle` examples for `import-osm` |
| `overpass_response.json` | Raw Overpass API response shape for exporter unit tests |

Live exports from `export-osm` should be written to `data/exports/` (gitignored), then imported with `import-osm`. Use `data/exports/osm_uk_ie_muslim.json` for the standard UK and Ireland snapshot.

See [docs/data/import-order.md](../../../docs/data/import-order.md) for the recommended import sequence.
