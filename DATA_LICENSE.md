# Public Data License

This document describes the intended license for **public normalized Directory data** —
mosque identity facts, published jamaat occurrences, freshness metadata, change feeds,
and bulk export files — when those datasets are published outside this private repository.

Application source code remains proprietary. See [LICENSE.md](LICENSE.md).

## Default license: Open Database License (ODbL) 1.0

Public Directory database exports are intended to be shared under the
[Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/).

ODbL is the default because OpenStreetMap-derived mosque discovery data in the Directory
is itself ODbL-licensed. Publishing an adapted database that incorporates ODbL data
requires a compatible share-alike license for the produced database.

### What ODbL covers

When public exports are released, you may:

- Share, adapt, and reuse the **public normalized database** (snapshots, CSV, NDJSON,
  changes feeds, and API responses that contain only public-safe fields)
- Produce works based on the database

Under ODbL terms you must:

- Attribute the Directory and upstream sources (see [ATTRIBUTION.md](ATTRIBUTION.md))
- Share any **produced database** you distribute under the same ODbL terms
- Keep the database open if you publicly use a substantial portion of it

Full legal terms: [https://opendatacommons.org/licenses/odbl/1-0/](https://opendatacommons.org/licenses/odbl/1-0/)

## API documentation and schemas

OpenAPI specifications and JSON Schema files under `docs/api/` are intended for public
reuse under [Creative Commons Attribution 4.0 (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)
when published separately from this private repository.

## What is **not** public data

The following remain **private operational data** and are not licensed for redistribution
under ODbL or any public data license:

- Raw source artifacts (HTML, PDF, images, partner dumps)
- Extraction prompts, private crawler configuration, and moderation notes
- Mosque claim contact details and private admin discovery leads
- Rows from sources marked `private_use_only`, `unknown`, or `blocked`
- Partner/platform data without explicit `public_redistribution_allowed` permission

Publication gates in the service enforce these exclusions in public API responses and bulk
exports. See [docs/adr/0003-source-publication-gates.md](docs/adr/0003-source-publication-gates.md).

## Partner and third-party data

Some rows may credit third-party sources (for example MyLocalMasjid, mosque standard feeds,
or mosque websites). Those facts appear in public exports **only when** the linked source
record has `public_redistribution_allowed` and the upstream terms permit normalized public
redistribution.

Restricted partner data must never be mixed into public snapshots. If a partner permits only
private use, their data stays out of public exports entirely.

## Export manifest

Bulk export `manifest.json` and `metadata.json` files include a `license_summary` and source
counts (`public_redistribution_allowed`, `excluded_restricted`) describing what entered each
dataset version.

## Pre-release notice

This repository is private and **no public data release has occurred yet**. This document
describes the intended license before any external publication. When the first public dataset
is published, the effective date and version will be recorded in export metadata and an ADR
update.
