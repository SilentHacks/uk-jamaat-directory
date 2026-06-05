# Attribution

Public Directory data and exports must credit the Directory and upstream sources that
contributed to published rows.

## Required Directory credit

When you use public Directory snapshots, API responses, or derivative databases, include:

> Data includes information from the UK Jamaat Directory
> ([https://github.com/SilentHacks/uk-jamaat-directory](https://github.com/SilentHacks/uk-jamaat-directory))
> available under the Open Database License (ODbL) 1.0.

Adjust the URL when a public project website replaces the repository link.

## Per-source attribution

Published mosque and timetable rows carry source provenance in API responses and export files.
Credit upstream sources when their data appears in material you redistribute.

| Source type | When it appears publicly | Attribution guidance |
|-------------|--------------------------|----------------------|
| OpenStreetMap | Mosque identity/discovery fields linked to OSM imports | © OpenStreetMap contributors, ODbL 1.0 |
| MyLocalMasjid | Only when `public_redistribution_allowed` | Credit MyLocalMasjid and link to the source URL recorded on the row |
| Standard feed | Mosque-published `/.well-known/uk-jamaat-directory.json` | Credit the mosque or feed publisher; link `source_url` when present |
| Mosque website | Deterministic extraction after manual approval | Credit the mosque; link `source_url` when present |
| Community submission | After moderation and publication | Credit UK Jamaat Directory community intake |
| Manual / admin | Operator-entered public records | Credit UK Jamaat Directory |

Synthetic test fixtures in this repository are not public data and must not be attributed as
live source coverage.

## Export attribution file

Each published dataset version includes `attribution.txt` in bulk exports. Treat that file as
the authoritative attribution list for that snapshot. The export `manifest.json` repeats
source counts and license summary metadata.

## What not to attribute as public Directory data

Do **not** present the following as ODbL-licensed Directory exports:

- Raw HTML/PDF artifacts or private crawl dumps
- Google Maps/Places discovery leads (admin-only hints)
- Partner data with `private_use_only` or `unknown` publication policy
- Claimant contact details from mosque ownership requests

## Corrections and opt-out

Mosques and data providers can report errors through the public contribution endpoints
documented in [README.md](README.md). Published corrections appear in the change feed for
the next dataset version.

For licensing or attribution disputes, contact the maintainers through the channel listed in
[SECURITY.md](SECURITY.md).
