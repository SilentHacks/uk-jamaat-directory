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
per-row source URLs using MiB IDs. Fetching must be single-threaded with the
project crawl user agent. Raw live downloads must not be committed.

## Consequences

- MiB can improve identity coverage and source overlap after OSM import.
- MiB-derived facts remain private by default under ADR 0003 gates.
- Attribution guidance is recorded in `ATTRIBUTION.md`.
- Any future decision to publish MiB-only facts must update this ADR with the
  effective terms and acknowledgement text.
