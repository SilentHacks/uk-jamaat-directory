# 0006: Schedule Validation And Publication

## Status

Accepted.

## Context

Imports create `schedule_candidates` privately. Public APIs and snapshots must only expose rows that passed validation, explicit publication, and source policy gates.

## Decision

1. **Explicit publication only** — imports never write public `schedule_occurrences`. Operators run `validate-candidates` then `publish-candidates` (admin HTTP in a later phase).

2. **Deterministic validation** — hard errors reject candidates; warnings are stored but may still be approved. AI extraction never auto-approves.

3. **Latest published dataset on reads** — public times endpoints return occurrences from the newest `dataset_versions` row with `status=published` only.

4. **Versioned publish batches** — each publish creates a new dataset version, writes occurrences, and appends `change_events` (including removals vs the previous published version).

5. **Prayer-window checks** — optional warnings only; calculated prayer times are never authoritative jamaat truth.

6. **Re-import idempotency** — duplicate artifacts still upsert candidates; unchanged rows are not duplicated.

## Consequences

- Operators must run validation and publication after imports with `public_redistribution_allowed`.
- Republish requires fresh approved candidates (typically re-import + validate).
- Overnight jamaat (isha after midnight) is not modeled in Phase 7 validation.
