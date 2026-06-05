# MuslimsInBritain fixtures

Synthetic fixtures for MuslimsInBritain import and exporter tests. Do not commit live MiB CSV or scraped page dumps.

## Acquisition spike notes

- Bulk source: `https://mosques.muslimsinbritain.org/gps-csv.php?includecomment=1`
- Format: CSV rows of `longitude,latitude,label,comment`
- Stable ID: suffix in comment, for example `AB24 3JD-ID:1`; normalized as `mib-1`
- Source URL: `https://mosques.muslimsinbritain.org/index.php?id=<id>`
- Label format: optional precision marker (`*` precise, `?` approximate), bracketed code, then display text
- Code key: capacity, women facilities, usage, theme, and management are decoded from the MiB `gps.php` key
- Scope: full UK and Ireland; country is derived from postcode/Eircode and coordinates
- Fetch policy: use the project crawl user agent and a single-threaded exporter; avoid committing raw live data

| File | Purpose |
|------|---------|
| `sample_export.json` | Normalized `MibImportBundle` examples for `import-mib` |
| `raw_poi_sample.csv` | Synthetic raw MiB CSV shape for adapter/exporter tests |
