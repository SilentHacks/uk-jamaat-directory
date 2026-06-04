# 0003: Source Publication Gates

## Status

Accepted.

## Context

The Directory may ingest data from mosque-owned feeds, MyLocalMasjid, platform feeds, OSM, charity registers, mosque websites, and community submissions.

Not every source necessarily permits public redistribution. MyLocalMasjid is the preferred primary mosque source, but normalized MLM-derived data should only be published if the agreement permits it.

## Decision

Every source must carry an explicit publication policy:

- `public_redistribution_allowed`
- `private_use_only`
- `unknown`
- `blocked`

Only rows derived from sources with `public_redistribution_allowed` may enter public APIs or snapshots.

## Consequences

Source adapters can be built and tested before legal terms are final, but publication/export services must enforce the gate centrally.

Tests must prove that unknown, private-only, and blocked sources cannot leak into public exports.
